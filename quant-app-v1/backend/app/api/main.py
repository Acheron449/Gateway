from __future__ import annotations

import asyncio
import math
import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import time
import json
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.rate_limit import limiter
from app.api.observability import RequestLoggingMiddleware
from app.api.error_aggregation import ErrorAggregator, scrub_error_text

from app.api.v1.analysis import router as analysis_router
from app.api.v1.agentic_lab import router as agentic_lab_router
from app.api.v1.auth import router as auth_router
from app.api.v1.quant import router as quant_router
from app.api.v1.backtest import router as backtest_router
from app.api.v1.bots import router as bots_router
from app.api.v1.catalogue import router as catalogue_router
from app.api.v1.divergence import router as divergence_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.journal import router as journal_router
from app.api.v1.llm import router as llm_router
from app.api.v1.news import quote_router, router as news_router
from app.api.openstock_routes import router as openstock_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.risk import router as risk_router
from app.api.v1.settings import router as settings_router
from app.api.v1.stocks import router as stocks_router
from app.api.v1.strategies import router as strategies_router
from app.api.v1.ai_trading import router as ai_trading_router
from app.api.v1.vault import router as vault_router
from app.api.v1.filings import router as filings_router
from app.api.v1.watchlists import router as watchlists_router
from app.api.v1.layouts import router as layouts_router
from app.api.v1.preferences import router as preferences_router
from app.api.v1.notices import router as notices_router
from app.services import database
from app.services.market_data import _alpaca_credentials, _stock_feed
from app.quant.recognition import find_pivots, detect_head_and_shoulders
from app.quant.technicals import calculate_wilder_rsi
from app.config import get_settings
from app.providers.registry import get_provider as get_registry_provider
from app.services.provenance import candle_provenance
from app.services.as_of import filter_timestamped_rows, normalize_as_of, parse_data_timestamp
from app.auth import _operator_identities, decode_token, get_current_user_optional, OptionalUser
from starlette.middleware.base import BaseHTTPMiddleware


def _yf():
    """Lazy import declared at the top of the file.

    yfinance is loaded on first use (history/quote fetches) rather than at
    API-import time, so booting the server never pays for the dependency.
    """
    import yfinance as yf

    return yf

# Rate limiter — configured in app.api.rate_limit so route modules can add
# stricter per-route budgets without importing this module.

# Security headers middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


def content_security_policy(env: str | None = None) -> str:
    """Build the CSP for an environment profile.

    Production does not run Vite's development client, so its script policy
    drops to ``'self'``. Local and test builds keep ``'unsafe-inline'`` and
    ``'unsafe-eval'`` because Vite's HMR client and React refresh runtime
    require them. ``env`` defaults to ``GATEWAY_ENV`` (falling back to local).
    """
    profile = (env or os.getenv("GATEWAY_ENV", "local")).lower()
    script_src = "'self'" if profile in ("production", "prod") else "'self' 'unsafe-inline' 'unsafe-eval'"
    return (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' ws: wss:;"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""
    
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        # HSTS for production (only if using HTTPS)
        env = os.getenv("GATEWAY_ENV", "local").lower()
        if env in ("production", "prod"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Content Security Policy (production excludes inline/eval scripts)
        response.headers["Content-Security-Policy"] = content_security_policy(env)
        return response


# Bridge between Alpaca (or a configured Finnhub quote feed) and WebSocket broadcast.
data_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
_ws_clients_lock = asyncio.Lock()
# each client entry is { 'ws': WebSocket, 'subs': set((symbol, tf_key), ...) }
_ws_clients: list[dict] = []

_lifespan_holder: dict[str, Any] = {}
RSI_PERIOD = 14


@asynccontextmanager
async def lifespan(app: FastAPI):

    ws_symbol = (os.getenv("QUANT_WS_SYMBOL", "AAPL") or "AAPL").upper()
    creds = _alpaca_credentials()

    async def alpaca_streamer():
        """Feed the queue from Alpaca minute bars inside the app's event loop."""
        from alpaca.data.live import StockDataStream

        buff: deque[dict[str, Any]] = deque(maxlen=30)

        api_key, secret_key = creds
        stream = StockDataStream(api_key, secret_key, raw_data=False, feed=_stock_feed())
        _lifespan_holder["alpaca_stream"] = stream

        async def handle_bar(data):
            buff.append({"close": data.close})
            rsi_val = 0.0
            if len(buff) >= RSI_PERIOD:
                df_rsi = pd.DataFrame(list(buff))
                series = calculate_wilder_rsi(df_rsi["close"], period=RSI_PERIOD)
                last = series.iloc[-1]
                if pd.notna(last):
                    rsi_val = float(last)

            payload = {
                "symbol": data.symbol,
                "price": float(data.close),
                "rsi": round(rsi_val, 2),
            }
            await data_queue.put(payload)

        stream.subscribe_bars(handle_bar, ws_symbol)
        logger.success(
            "Alpaca WS feed started → queue (minute bars): {} (feed={}).",
            ws_symbol,
            "SIP" if os.getenv("ALPACA_STOCK_FEED", "").upper() == "SIP" else "IEX",
        )
        await stream._run_forever()

    TF_KEYS = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400}

    async def aggregation_loop():
        """Aggregate incoming price updates into timeframe candles and push to subscribed WS clients.

        Messages in data_queue are expected to be dicts: { 'symbol': str, 'price': float, 'rsi': float }
        """
        last_candles: dict[tuple[str, str], dict[str, Any]] = {}
        while True:
            msg = await data_queue.get()
            try:
                symbol = (msg.get('symbol') or '').upper()
                price = float(msg.get('price'))
            except Exception:
                continue
            ts = int(time.time())
            # For each configured timeframe, update bucket
            for tf_key, step in TF_KEYS.items():
                bucket = (ts // step) * step
                key = (symbol, tf_key)
                prev = last_candles.get(key)
                if prev is None or bucket > prev['time']:
                    # close previous candle
                    if prev is not None:
                        closed = prev.copy()
                        # broadcast closed candle to subscribers
                        payload = {'type': 'candle_closed', 'symbol': symbol, 'tf': tf_key, 'candle': closed}
                        async with _ws_clients_lock:
                            clients = list(_ws_clients)
                        for client in clients:
                            try:
                                subs = client.get('subs', set())
                                if (symbol, tf_key) in subs or (symbol, '*') in subs or ('*', tf_key) in subs or ('*', '*') in subs:
                                    await client['ws'].send_json(payload)
                            except Exception:
                                async with _ws_clients_lock:
                                    if client in _ws_clients:
                                        _ws_clients.remove(client)
                    # create new candle
                    new_candle = {'time': bucket, 'open': price, 'high': price, 'low': price, 'close': price}
                    
                    # Build history for pattern detection (storing last 50 ticks for context)
                    if key not in last_candles:
                        last_candles[key] = []
                    
                    # Update history with new candle
                    last_candles[key].append(new_candle)
                    if len(last_candles[key]) > 50:
                        last_candles[key].pop(0)
                    
                    # Data needed for pattern recognition
                    history_df = pd.DataFrame(last_candles[key])
                    
                    # Check for patterns
                    pivots = find_pivots(history_df)
                    patterns = detect_head_and_shoulders(pivots)
                    
                    pattern_detected = len(patterns) > 0
                    pattern_label = patterns[0].type if pattern_detected else None
                    
                    # Broadcast initial candle update
                    payload = {
                        'type': 'candle_update', 
                        'symbol': symbol, 
                        'tf': tf_key, 
                        'candle': new_candle,
                        'rsi': round(rsi_val, 2),
                        'pattern_detected': pattern_detected,
                        'pattern_label': pattern_label
                    }
                    async with _ws_clients_lock:
                        clients = list(_ws_clients)
                    for client in clients:
                        try:
                            subs = client.get('subs', set())
                            if (symbol, tf_key) in subs or (symbol, '*') in subs or ('*', tf_key) in subs or ('*', '*') in subs:
                                await client['ws'].send_json(payload)
                        except Exception:
                            async with _ws_clients_lock:
                                if client in _ws_clients:
                                    _ws_clients.remove(client)
                else:
                    # update existing candle
                    updated = prev.copy()
                    updated['close'] = price
                    updated['high'] = max(updated['high'], price)
                    updated['low'] = min(updated['low'], price)
                    
                    # Update the history buffer
                    last_candles[key][-1] = updated
                    
                    # Check for patterns
                    pattern_detected = False
                    pattern_label = None
                    
                    # Run detection on the updated history
                    history_df = pd.DataFrame(last_candles[key])
                    pivots = find_pivots(history_df)
                    patterns = detect_head_and_shoulders(pivots)
                    
                    pattern_detected = len(patterns) > 0
                    pattern_label = patterns[0].type if pattern_detected else None
                    
                    # broadcast updated candle
                    payload = {
                        'type': 'candle_update', 
                        'symbol': symbol, 
                        'tf': tf_key, 
                        'candle': updated,
                        'rsi': round(rsi_val, 2),
                        'pattern_detected': pattern_detected,
                        'pattern_label': pattern_label
                    }
                    async with _ws_clients_lock:
                        clients = list(_ws_clients)
                    for client in clients:
                        try:
                            subs = client.get('subs', set())
                            if (symbol, tf_key) in subs or (symbol, '*') in subs or ('*', tf_key) in subs or ('*', '*') in subs:
                                await client['ws'].send_json(payload)
                        except Exception:
                            async with _ws_clients_lock:
                                if client in _ws_clients:
                                    _ws_clients.remove(client)

    tasks: list[asyncio.Task] = []
    tasks.append(asyncio.create_task(aggregation_loop(), name="ws-aggregation-loop"))

    finnhub_key = os.getenv('FINNHUB_API_KEY')

    if creds:
        tasks.append(asyncio.create_task(alpaca_streamer(), name="alpaca-queue-feed"))
    elif finnhub_key:
        logger.info("Alpaca creds not set — using configured Finnhub quote feed for /ws/trading.")

        async def finnhub_feeder(api_key: str):
            """Stream configured Finnhub quotes without exposing the API key."""
            import httpx

            buff: deque[dict[str, Any]] = deque(maxlen=30)
            headers = {"X-Finnhub-Token": api_key}
            async with httpx.AsyncClient(timeout=10.0) as client:
                while True:
                    try:
                        await asyncio.sleep(1.0)
                        response = await client.get(
                            "https://finnhub.io/api/v1/quote",
                            params={"symbol": ws_symbol},
                            headers=headers,
                        )
                        if response.status_code != 200:
                            raise RuntimeError(f"Finnhub quote error: {response.status_code}")
                        data = response.json()
                        price_value = data.get("c")
                        if price_value is None:
                            raise RuntimeError("Finnhub quote response did not include a current price")
                        price = float(price_value)
                        if not math.isfinite(price) or price <= 0:
                            raise RuntimeError("Finnhub quote response did not include a valid current price")
                        buff.append({"close": price})
                        rsi_val = 0.0
                        if len(buff) >= RSI_PERIOD:
                            rsi_series = calculate_wilder_rsi(pd.DataFrame(list(buff))["close"], period=RSI_PERIOD)
                            last = rsi_series.iloc[-1]
                            if pd.notna(last):
                                rsi_val = float(last)

                        await data_queue.put(
                            {
                                "symbol": ws_symbol,
                                "price": round(price, 4),
                                "rsi": round(rsi_val, 2),
                            }
                        )
                    except Exception:
                        logger.debug("Finnhub feeder rejected an invalid quote response")
                        await asyncio.sleep(2.0)

        tasks.append(asyncio.create_task(finnhub_feeder(finnhub_key), name="finnhub-queue-feed"))
    else:
        logger.warning(
            "Alpaca credentials and FINNHUB_API_KEY are not set; /ws/trading has no market-data feed."
        )

    # Resume each owner's AI trader if it was left enabled (AI Trading section).
    try:
        from app.services import ai_trading as _ai_trading

        resumed = _ai_trading.autostart()
        if resumed:
            logger.info("AI trading loops resumed for {} owner(s)", len(resumed))
    except Exception as exc:
        logger.warning("AI trading autostart skipped: {}", exc)

    yield

    try:
        from app.services import ai_trading as _ai_trading

        _ai_trading.shutdown()
    except Exception:
        pass

    stream_obj = _lifespan_holder.pop("alpaca_stream", None)
    if stream_obj is not None:
        try:
            await stream_obj.stop_ws()
        except Exception as exc:
            logger.debug("Alpaca stream stop_ws: {}", exc)

    for t in tasks:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


settings = get_settings()
app = FastAPI(title="Gateway API", version="0.2.0", lifespan=lifespan)


class PrivateDataGateMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        """Authenticate and fail closed for shared stores until ownership ships."""
        path = request.url.path.rstrip("/") or "/"
        # /strategies, /journal, /portfolio and /ai-trading are deliberately
        # absent: every one of their routes derives its owner from CurrentUser,
        # so they are scoped per request rather than fail-closed behind the
        # shared-store gate.
        private_prefixes = ("/vault", "/llm")
        operator_prefixes = ("/risk", "/settings/providers")
        private = any(path == prefix or path.startswith(prefix + "/") for prefix in private_prefixes)
        operator_only = any(path == prefix or path.startswith(prefix + "/") for prefix in operator_prefixes)
        if path.startswith("/forecast/kronos/install/") or path == "/forecast/kronos/install":
            return await call_next(request)
        if not private and not operator_only:
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token.strip():
            return JSONResponse(
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                content={"detail": "Not authenticated"},
            )
        token_data = decode_token(token.strip())
        if token_data is None or token_data.exp < datetime.now(timezone.utc):
            return JSONResponse(
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
                content={"detail": "Invalid or expired token"},
            )

        if operator_only:
            if (token_data.issuer, token_data.subject) not in _operator_identities():
                return JSONResponse(status_code=403, content={"detail": "Operator access required"})
            return await call_next(request)

        # Shared stores are denied for every authenticated account until their
        # owner-scoped repositories are deployed. This middleware is scoped to
        # HTTP; WebSocket routes perform first-frame auth and their own stopgap.
        return JSONResponse(
            status_code=503,
            content={"detail": "Private data unavailable until account isolation is enabled"},
        )


app.add_middleware(PrivateDataGateMiddleware)

# Enforce the shared limiter's default budget. Registered before the header
# and CORS middlewares so those still wrap 429 responses.
app.add_middleware(SlowAPIMiddleware)

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# CORS for browser clients: the static frontend (e.g. :3000) calls this API
# cross-origin (e.g. http://127.0.0.1:8000 baked into the built bundle), so
# without CORS the browser blocks every response and fetches report
# "Failed to fetch". Registered after SecurityHeadersMiddleware so it sits
# outermost — preflight OPTIONS requests are answered here, and responses
# carry both CORS and security headers. Origins are configurable via
# GATEWAY_CORS_ORIGINS (comma-separated) for non-localhost deployments.
_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "GATEWAY_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Registered last so it is the outermost middleware: every response, including
# 401/403/429 and CORS preflight, is logged and carries X-Request-ID (NFR-21).
app.add_middleware(RequestLoggingMiddleware)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

error_aggregator = ErrorAggregator.from_env()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fixed 500 envelope; optional aggregation gets only scrubbed text."""
    aggregator_event = error_aggregator.capture(request, exc)
    request_id = getattr(request.state, "request_id", None)
    logger.bind(
        request_id=request_id,
        error_type=type(exc).__name__,
        error_id=aggregator_event.error_id if aggregator_event else None,
    ).error("unhandled request error: {}", scrub_error_text(f"{type(exc).__name__}: {exc}"))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={"X-Request-ID": request_id} if request_id else None,
    )

# Public routes (no authentication required)
app.include_router(auth_router)
app.include_router(catalogue_router)  # Public catalogue access
app.include_router(news_router)  # Public news/calendar access
app.include_router(filings_router)  # SEC filings feed for the Overview card
app.include_router(quote_router)  # Public normalized quote access
app.include_router(strategies_router)  # Strategy Studio (owner-scoped per request)
app.include_router(journal_router)  # Trade Journal (owner-scoped per request)
app.include_router(risk_router)  # Risk Dashboard (operator-gated global configuration)
app.include_router(divergence_router)  # Divergence Scorecards
app.include_router(settings_router)  # Global provider settings (operator-gated)
app.include_router(vault_router, dependencies=[Depends(get_current_user_optional)])  # Encrypted secrets vault (also gated until owner isolation)
app.include_router(ai_trading_router)  # AI auto-trading (owner-scoped per request)
app.include_router(llm_router)  # BYOK/chat gated until durable owner store is deployed
app.include_router(agentic_lab_router)  # Agentic Trading Lab (backtests + stats)
app.include_router(openstock_router)  # OpenStock Symbol Search & Adanos Sentiment

# Protected routes (authentication required)
app.include_router(watchlists_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(layouts_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(preferences_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(notices_router)
app.include_router(stocks_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(analysis_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(backtest_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(quant_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(bots_router, dependencies=[Depends(get_current_user_optional)])
# NOTE: portfolio_router is included without a router-level dependency because
# it contains a WebSocket route. Every HTTP handler takes CurrentUser and
# resolves only that account's `paper_<user.id>` book; the WebSocket handler
# authenticates from its first frame and reports streaming as unavailable.
app.include_router(forecast_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(portfolio_router)
# Fail closed: live/broker account routes remain deliberately unmounted until
# authenticated account ownership and durable intent recovery are implemented.
# Keep the router module importable for tests and legacy internal references.


@app.get("/")
def home() -> dict:
    return {"status": "Quant Engine Running"}


def _database_component() -> dict[str, Any]:
    """Readiness probe for the SQLite store: open it and run a trivial query.

    The failure body carries a fixed message, never the exception text, so a
    path, DSN or driver detail cannot leak (NFR-11).
    """
    started = time.perf_counter()
    try:
        with database.get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        status = "ok"
    except Exception:
        logger.warning("health: database readiness check failed")
        status = "failed"
    return {
        "status": status,
        "detail": None if status == "ok" else "database unavailable",
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _health_report() -> tuple[dict[str, Any], bool]:
    components = {"database": _database_component()}
    ready = all(component["status"] == "ok" for component in components.values())
    return (
        {
            "status": "ok" if ready else "degraded",
            "service": "gateway-api",
            "version": app.version,
            "environment": settings.environment,
            "execution_mode": settings.execution_mode,
            "capabilities": settings.capabilities,
            "components": components,
        },
        ready,
    )


@app.get("/health/live")
async def health_live() -> dict[str, Any]:
    """Liveness: the process is serving requests; never touches dependencies."""
    return {"status": "ok", "service": "gateway-api", "version": app.version}


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    """Readiness: 200 only when every probed dependency answers."""
    body, ready = _health_report()
    return JSONResponse(status_code=200 if ready else 503, content=body)


@app.get("/health")
async def health() -> JSONResponse:
    """Readiness plus the environment and capability report required by NFR-20."""
    body, ready = _health_report()
    return JSONResponse(status_code=200 if ready else 503, content=body)


TF_TO_SECONDS = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '5h': 18000, '1d': 86400}


def _resample_candles(candles: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    """Resample OHLC candles into a requested timeframe."""
    tf_key = (timeframe or '1h').lower()
    step = TF_TO_SECONDS.get(tf_key, 3600)
    if not candles:
        return []

    bucketed: dict[int, dict[str, Any]] = {}
    for candle in candles:
        ts = int(candle.get('time', 0))
        bucket = (ts // step) * step
        volume = float(candle.get('volume', 0.0) or 0.0)
        if bucket not in bucketed:
            bucketed[bucket] = {
                'time': bucket,
                'open': float(candle.get('open', 0.0)),
                'high': float(candle.get('high', 0.0)),
                'low': float(candle.get('low', 0.0)),
                'close': float(candle.get('close', 0.0)),
                'volume': volume,
            }
            continue
        entry = bucketed[bucket]
        entry['high'] = max(entry['high'], float(candle.get('high', entry['high'])))
        entry['low'] = min(entry['low'], float(candle.get('low', entry['low'])))
        entry['close'] = float(candle.get('close', entry['close']))
        entry['volume'] = entry.get('volume', 0.0) + volume
    ordered = sorted(bucketed.values(), key=lambda x: x['time'])
    return ordered


YF_TF_MAP: dict[str, tuple[str, str]] = {
    # tf -> (yfinance interval, yfinance period)
    '1m': ('1m', '7d'),
    '5m': ('5m', '1mo'),
    '15m': ('15m', '1mo'),
    '30m': ('30m', '1mo'),
    '1h': ('1h', '3mo'),
    '4h': ('1h', '6mo'),  # resampled to 4h below
    '5h': ('1h', '6mo'),  # resampled to 5h below
    '1d': ('1d', '2y'),
    '1wk': ('1wk', '5y'),
}


def _fetch_history_yfinance_sync(
    ticker: str,
    tf: str,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Credentials-free historical bars via yfinance (Gateway dependency).

    Used when Alpaca credentials are absent so the native chart keeps working
    without a paid data feed. Raises HTTPException(502) on empty responses.
    """
    yf = _yf()

    interval, period = YF_TF_MAP.get((tf or '1h').lower(), YF_TF_MAP['1h'])
    cutoff = normalize_as_of(as_of)
    frame = yf.Ticker(ticker.upper()).history(
        period=period,
        interval=interval,
        end=cutoff.replace(tzinfo=None) if cutoff else None,
        auto_adjust=False,
    )
    if frame is None or frame.empty:
        raise HTTPException(status_code=502, detail=f"No history data available for {ticker.upper()}")

    candles: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        ts = index.timestamp()
        close = float(row['Close'])
        if not math.isfinite(close) or close <= 0:
            continue
        volume = float(row.get('Volume', 0) or 0)
        candles.append(
            {
                'time': int(ts),
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': close,
                'volume': volume,
            }
        )
    candles.sort(key=lambda c: c['time'])
    return filter_timestamped_rows(candles, as_of=as_of)


# Chart data providers selectable by the UI (`?provider=`).
_HISTORY_PROVIDER_IDS: dict[str, str] = {
    "yahoo": "Yahoo Finance",
    "yfinance": "Yahoo Finance",
    "yahoo finance": "Yahoo Finance",
    "yahoo-finance": "Yahoo Finance",
    "ccxt": "CCXT",
    "kraken": "CCXT",  # ccxt backs onto a configurable exchange (default: kraken)
    "alpaca": "Alpaca",
    "tradingview": "TradingView",
    "tv": "TradingView",
    "alltick": "AllTick",
    "finnhub": "Finnhub",
    "lse": "London Strategic Edge",
    "london strategic edge": "London Strategic Edge",
    "londonstrategicedge": "London Strategic Edge",
    "london-strategic-edge": "London Strategic Edge",
}


def _canonical_history_provider(provider: str | None) -> str:
    """Resolve a user/provider id (or display name) to a canonical name."""
    wanted = (provider or "Yahoo Finance").strip().casefold()
    if not wanted:
        return "Yahoo Finance"
    canonical = _HISTORY_PROVIDER_IDS.get(wanted)
    if canonical:
        return canonical
    for name in ("Yahoo Finance", "CCXT", "Alpaca", "TradingView", "AllTick", "Finnhub", "London Strategic Edge"):
        if name.casefold() == wanted:
            return name
    return "Yahoo Finance"


def _alltick_available() -> bool:
    try:
        instance = get_registry_provider("AllTick")
        return bool(instance and instance.is_configured)
    except Exception:
        return False


def _ccxt_available() -> bool:
    """True when the ccxt backup provider is importable in this environment."""
    try:
        instance = get_registry_provider("CCXT")
        return bool(instance and instance.is_configured)
    except Exception:
        return False


def _lse_available() -> bool:
    """True when a London Strategic Edge key is configured (stored or env)."""
    try:
        instance = get_registry_provider("London Strategic Edge")
        return bool(instance and instance.is_configured)
    except Exception:
        return False


def _finnhub_available() -> bool:
    """True when a Finnhub key is configured (stored or env)."""
    try:
        instance = get_registry_provider("Finnhub")
        return bool(instance and instance.is_configured)
    except Exception:
        return False


def _ccxt_history_backup_sync(
    ticker: str,
    tf: str,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]] | None:
    """CCXT fallback used when yfinance fails on a crypto symbol.

    Returns None (instead of raising) for non-crypto symbols or any ccxt
    error, so the caller can surface the original yfinance failure.
    """
    try:
        instance = get_registry_provider("CCXT")
        if instance is None or not instance.is_configured:
            return None
        interval, period = YF_TF_MAP.get((tf or "1h").lower(), YF_TF_MAP["1h"])
        rows = asyncio.run(
            instance.history(ticker.upper(), interval, period, **({"as_of": as_of} if as_of else {}))
        )
        return filter_timestamped_rows(_normalize_history_rows(rows, as_of=as_of), as_of=as_of) or None
    except Exception as exc:
        logger.warning(f"ccxt history backup failed for {ticker.upper()}: {exc}")
        return None


def _history_provider_catalogue() -> list[dict[str, Any]]:
    """Providers the interactive chart can be pointed at (default: Yahoo Finance)."""
    return [
        {
            "id": "yahoo",
            "name": "Yahoo Finance",
            "detail": "Free Yahoo Finance bars via yfinance · no API key",
            "available": True,
            "is_default": True,
        },
        {
            "id": "ccxt",
            "name": "CCXT",
            "detail": "Public exchange OHLCV via ccxt (crypto pairs) · no API key · backup for yfinance",
            "available": _ccxt_available(),
            "is_default": False,
        },
        {
            "id": "tradingview",
            "name": "TradingView",
            "detail": "TradingView public datafeed · no API key",
            "available": True,
            "is_default": False,
        },
        {
            "id": "alltick",
            "name": "AllTick",
            "detail": "AllTick K-lines · API key required",
            "available": _alltick_available(),
            "is_default": False,
        },
        {
            "id": "alpaca",
            "name": "Alpaca",
            "detail": "Alpaca market-data bars · API keys required",
            "available": bool(_alpaca_credentials()),
            "is_default": False,
        },
        {
            "id": "finnhub",
            "name": "Finnhub",
            "detail": "Finnhub OHLCV candles · API key required · premium-gated",
            "available": _finnhub_available(),
            "is_default": False,
        },
        {
            "id": "lse",
            "name": "London Strategic Edge",
            "detail": "London Strategic Edge vault candles (stocks to 2003, FX 2009, crypto 2017) · free API key",
            "available": _lse_available(),
            "is_default": False,
        },
    ]


@app.get("/history/providers")
async def get_history_providers() -> dict[str, Any]:
    """List chart data providers so the UI can offer a picker."""
    return {"providers": _history_provider_catalogue(), "default": "yahoo"}


def _history_time_to_epoch(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    timestamp = getattr(value, "timestamp", None)
    if callable(timestamp):
        try:
            return int(timestamp())
        except (ValueError, OSError, OverflowError):
            return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _normalize_history_rows(
    rows: Any,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Normalize provider candle rows, rejecting unknown times in cutoff mode."""
    cutoff = normalize_as_of(as_of)
    candles: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, dict):
            raw_time = row.get("time", row.get("timestamp"))
            raw_ohlc = (row.get("open"), row.get("high"), row.get("low"), row.get("close"))
            raw_volume = row.get("volume", 0)
        else:
            raw_time = getattr(row, "time", None)
            raw_ohlc = tuple(getattr(row, key, None) for key in ("open", "high", "low", "close"))
            raw_volume = getattr(row, "volume", 0)
        if cutoff is not None:
            parsed_time = parse_data_timestamp(raw_time)
            if parsed_time is None or parsed_time > cutoff:
                continue
            epoch = int(parsed_time.timestamp())
        else:
            epoch = _history_time_to_epoch(raw_time)
        try:
            open_, high, low, close = (float(value) for value in raw_ohlc)
        except (TypeError, ValueError):
            continue
        if epoch is None or not math.isfinite(close) or close <= 0:
            continue
        candles.append(
            {
                "time": epoch,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": float(raw_volume or 0),
            }
        )
    candles.sort(key=lambda candle: candle["time"])
    return candles


async def _fetch_history_alt_provider_sync(
    provider: str,
    ticker: str,
    tf: str,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]] | None:
    """Fetch bars from a non-Yahoo provider; None when unavailable/empty."""
    if provider == "Alpaca":
        creds = _alpaca_credentials()
        if not creds:
            return None
        if as_of is None:
            return await asyncio.to_thread(_fetch_history_chart_sync, creds[0], creds[1], ticker.upper())
        return await asyncio.to_thread(
            _fetch_history_chart_sync, creds[0], creds[1], ticker.upper(), as_of=as_of
        )

    if provider in ("Finnhub", "TradingView", "AllTick", "CCXT", "London Strategic Edge"):
        instance = get_registry_provider(provider)
        if instance is None or not instance.is_configured:
            return None
        interval, _period = YF_TF_MAP.get((tf or "1h").lower(), YF_TF_MAP["1h"])
        rows = await instance.history(
            ticker.upper(),
            interval,
            "1y",
            **({"as_of": as_of} if as_of is not None else {}),
        )
        return filter_timestamped_rows(_normalize_history_rows(rows, as_of=as_of), as_of=as_of)

    return None


# Bar limits (SRS FR-D6): one request never returns more than 20k rows, and
# an over-limit request is refused with a reason instead of silently truncated.
HISTORY_MAX_BARS = 20_000
HISTORY_MIN_BARS = 1
_CRYPTO_QUOTES = ("USD", "USDT", "USDC", "EUR", "BTC", "ETH")


def _is_crypto_symbol(ticker: str) -> bool:
    """True for pair-style crypto symbols (BTC-USD, ETH-USDT, BTCUSDT)."""
    sym = (ticker or "").strip().upper()
    if not sym:
        return False
    if "-" in sym:
        return sym.rsplit("-", 1)[-1] in _CRYPTO_QUOTES
    return any(sym.endswith(quote) and len(sym) > len(quote) for quote in ("USDT", "USDC"))


def _bar_limit_error(limit: int) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "bar_limit",
            "message": f"limit must be between {HISTORY_MIN_BARS} and {HISTORY_MAX_BARS} bars",
            "requested": limit,
            "max_bars": HISTORY_MAX_BARS,
        },
    )


@app.get("/history/{ticker}")
async def get_history(
    ticker: str,
    tf: str = "1h",
    limit: int = 500,
    provider: str = "Yahoo Finance",
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return historical bars for the chart from one explicitly chosen source.

    Yahoo Finance (yfinance) is the single default source; CCXT is reserved
    for crypto pairs when Yahoo cannot answer. A provider the caller names is
    never silently replaced, so the provenance on every bar always describes
    the source that actually produced it.
    """
    if limit < HISTORY_MIN_BARS or limit > HISTORY_MAX_BARS:
        raise _bar_limit_error(limit)
    try:
        as_of = normalize_as_of(as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    symbol = (ticker or "").strip().upper()
    chosen = _canonical_history_provider(provider)
    chart_data: list[dict[str, Any]] | None = None
    source = "yfinance"
    attempted: list[str] = []

    if chosen != "Yahoo Finance":
        attempted.append(chosen)
        try:
            chart_data = await _fetch_history_alt_provider_sync(chosen, ticker, tf, as_of=as_of)
        except Exception as exc:
            logger.warning(f"history provider '{chosen}' failed for {symbol}: {exc}")
            chart_data = None
        if chart_data:
            source = chosen.casefold().replace(" ", "-")
    else:
        attempted.append("yfinance")
        try:
            if as_of is None:
                chart_data = await asyncio.to_thread(_fetch_history_yfinance_sync, symbol, tf)
            else:
                chart_data = await asyncio.to_thread(
                    _fetch_history_yfinance_sync, symbol, tf, as_of=as_of
                )
        except Exception as exc:
            logger.warning(f"yfinance history failed for {symbol}: {exc}")
            chart_data = None
        if not chart_data and _is_crypto_symbol(symbol):
            attempted.append("ccxt")
            if as_of is None:
                chart_data = await asyncio.to_thread(_ccxt_history_backup_sync, symbol, tf)
            else:
                chart_data = await asyncio.to_thread(
                    _ccxt_history_backup_sync, symbol, tf, as_of=as_of
                )
            if chart_data:
                source = "ccxt"

    if not chart_data:
        raise HTTPException(
            status_code=502 if chosen == "Yahoo Finance" else 503,
            detail={
                "code": "source_unavailable" if chosen == "Yahoo Finance" else "provider_unavailable",
                "message": f"No history data available for {symbol} from {chosen}",
                "provider": chosen,
                "attempted": attempted,
                "symbol": symbol,
            },
        )

    chart_data = filter_timestamped_rows(chart_data, as_of=as_of)
    resampled = filter_timestamped_rows(_resample_candles(chart_data, tf), as_of=as_of)
    if resampled:
        resampled = resampled[-limit:]
    coverage = f"{'crypto' if _is_crypto_symbol(symbol) else 'US equities'} / {tf}"
    return [
        {
            **candle,
            **candle_provenance(
                source=source,
                data_time=int(candle["time"]),
                coverage=coverage,
            ),
        }
        for candle in resampled
    ]


@app.get("/market/{ticker}/history")
async def get_market_history(
    ticker: str,
    tf: str = "1h",
    limit: int = 500,
    provider: str = "Yahoo Finance",
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    return await get_history(ticker=ticker, tf=tf, limit=limit, provider=provider, as_of=as_of)


_quotes_cache: dict[str, Any] = {"at": 0.0, "rows": []}
# Short default so the user-selected data provider is polled frequently and
# quotes stay accurate; GATEWAY_QUOTES_TTL tunes it per deployment.
_QUOTES_TTL_SECONDS = float(os.getenv("GATEWAY_QUOTES_TTL", "10"))


def _fetch_quotes_yfinance_sync(symbols: list[str]) -> list[dict[str, Any]]:
    """Batch last-quote snapshot via yfinance for the ticker strip."""
    yf = _yf()

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        sym = symbol.strip().upper()
        if not sym:
            continue
        try:
            fast = yf.Ticker(sym).fast_info
            price = float(fast.last_price or 0)
            prev = float(fast.previous_close or 0)
        except Exception:
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        change = price - prev if prev > 0 else 0.0
        change_pct = (change / prev * 100.0) if prev > 0 else 0.0
        rows.append(
            {
                "symbol": sym,
                "price": round(price, 4),
                "change": round(change, 4),
                "change_pct": round(change_pct, 2),
            }
        )
    return rows


@app.get("/quotes")
async def get_quotes(symbols: str = "") -> dict[str, Any]:
    """Batch quote snapshot (last price, change, change%) for the ticker strip.

    Results are cached briefly to stay well inside free data-feed limits.
    """
    requested = [s for s in (symbols or "").split(",") if s.strip()][:30]
    if not requested:
        return {"quotes": [], "status": "available", "message": None}

    now = time.time()
    # Merge-cache per symbol: callers request different baskets (watchlists)
    # within one TTL, so only fetch symbols we don't already have fresh.
    cached: dict[str, Any] = {
        r["symbol"]: r for r in _quotes_cache.get("rows", []) if isinstance(r, dict) and r.get("symbol")
    }
    if now - float(_quotes_cache.get("at", 0.0)) >= _QUOTES_TTL_SECONDS:
        cached = {}

    missing = [s for s in requested if s not in cached]
    if missing:
        fetched = await asyncio.to_thread(_fetch_quotes_yfinance_sync, missing)
        cached.update({r["symbol"]: r for r in fetched})
        _quotes_cache["at"] = now
        _quotes_cache["rows"] = list(cached.values())

    quotes = [cached[s] for s in requested if s in cached]
    return {
        "quotes": quotes,
        "status": "available" if quotes else "unavailable",
        "message": None if quotes else "No quote data available (market closed or feed unreachable)",
    }


def _fetch_history_chart_sync(
    api_key: str,
    secret_key: str,
    ticker: str,
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(api_key, secret_key)
    end = normalize_as_of(as_of) or datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    request_params = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Hour,
        start=start,
        end=end,
    )

    bars = client.get_stock_bars(request_params)
    if isinstance(bars, dict):
        raise HTTPException(
            status_code=502,
            detail="Unexpected Alpaca response shape.",
        )

    row_list = bars.data.get(ticker, [])
    if not row_list and bars.data:
        for symbol_key, lst in bars.data.items():
            if symbol_key.upper() == ticker.upper():
                row_list = lst
                break
        if not row_list:
            fallback = tuple(bars.data.keys())
            if len(fallback) == 1:
                row_list = bars.data[fallback[0]]

    chart_data = []
    for bar in row_list:
        ts = bar.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        chart_data.append(
            {
                "time": int(ts.timestamp()),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
            }
        )
    chart_data.sort(key=lambda c: c["time"])
    return filter_timestamped_rows(chart_data, as_of=as_of)


@app.websocket("/ws/trading")
async def websocket_trading(websocket: WebSocket) -> None:
    """Authenticated live symbol/timeframe subscriptions; JWT is first-frame only."""
    if websocket.query_params.get("token"):
        await websocket.close(code=4001, reason="Token query parameters are not accepted")
        return
    await websocket.accept()
    try:
        auth_message = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        await websocket.close(code=4001, reason="Authentication required")
        return
    if not isinstance(auth_message, dict) or auth_message.get("type") != "authenticate":
        await websocket.close(code=4001, reason="Authentication required")
        return
    token = auth_message.get("token")
    if not isinstance(token, str) or not token.strip():
        await websocket.close(code=4001, reason="Authentication required")
        return
    token_data = decode_token(token.strip())
    if not token_data or token_data.exp < datetime.now(timezone.utc):
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    client = {"ws": websocket, "subs": set(), "user_id": token_data.user_id}
    async with _ws_clients_lock:
        _ws_clients.append(client)
    await websocket.send_json({"type": "authenticated"})
    try:
        while True:
            text = await websocket.receive_text()
            try:
                payload = json.loads(text)
                if not isinstance(payload, dict):
                    continue
                action = payload.get("action")
                if action == "subscribe":
                    symbol = (payload.get("symbol") or "*").upper()
                    timeframe = payload.get("tf") or "*"
                    client["subs"].add((symbol, timeframe))
                    await websocket.send_json({"type": "subscribed", "symbol": symbol, "tf": timeframe})
                elif action == "unsubscribe":
                    symbol = (payload.get("symbol") or "*").upper()
                    timeframe = payload.get("tf") or "*"
                    client["subs"].discard((symbol, timeframe))
                    await websocket.send_json({"type": "unsubscribed", "symbol": symbol, "tf": timeframe})
                elif action == "ping":
                    await websocket.send_json({"type": "pong"})
            except (json.JSONDecodeError, AttributeError):
                continue
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_clients_lock:
            if client in _ws_clients:
                _ws_clients.remove(client)
