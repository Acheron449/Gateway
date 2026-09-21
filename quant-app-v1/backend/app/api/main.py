from __future__ import annotations

import asyncio
import math
import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pandas_ta as ta
import time
import json
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.api.v1.analysis import router as analysis_router
from app.api.v1.auth import router as auth_router
from app.api.v1.backtest import router as backtest_router
from app.api.v1.catalogue import router as catalogue_router
from app.api.v1.divergence import router as divergence_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.journal import router as journal_router
from app.api.v1.live import router as live_router
from app.api.v1.news import quote_router, router as news_router
from app.api.openbb_routes import router as openbb_router
from app.api.v1.portfolio import router as portfolio_router
from app.api.v1.risk import router as risk_router
from app.api.v1.settings import router as settings_router
from app.api.v1.stocks import router as stocks_router
from app.api.v1.strategies import router as strategies_router
from app.api.v1.watchlists import router as watchlists_router
from app.api.v1.layouts import router as layouts_router
from app.api.v1.preferences import router as preferences_router
from app.services.market_data import _alpaca_credentials, _stock_feed
from app.quant.recognition import find_pivots, detect_head_and_shoulders
from app.config import get_settings
from app.services.provenance import candle_provenance
from app.auth import get_current_user_optional, OptionalUser

# Rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute", "1000/hour"])

# Security headers middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


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
        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' ws: wss:;"
        )
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
                series = ta.rsi(df_rsi["close"], length=RSI_PERIOD)
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
                            rsi_series = ta.rsi(pd.DataFrame(list(buff))["close"], length=RSI_PERIOD)
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

    yield

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

# Add security headers middleware
app.add_middleware(SecurityHeadersMiddleware)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Public routes (no authentication required)
app.include_router(auth_router)
app.include_router(catalogue_router)  # Public catalogue access
app.include_router(news_router)  # Public news/calendar access
app.include_router(quote_router)  # Public normalized quote access
app.include_router(strategies_router)  # Strategy Studio
app.include_router(journal_router)  # Trade Journal
app.include_router(risk_router)  # Risk Dashboard
app.include_router(divergence_router)  # Divergence Scorecards
app.include_router(settings_router)  # Settings
app.include_router(openbb_router)  # OpenBB Data Integration

# Protected routes (authentication required)
app.include_router(watchlists_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(layouts_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(preferences_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(stocks_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(analysis_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(backtest_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(forecast_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(portfolio_router, dependencies=[Depends(get_current_user_optional)])
app.include_router(live_router, dependencies=[Depends(get_current_user_optional)])


@app.get("/")
def home() -> dict:
    return {"status": "Quant Engine Running"}


@app.get("/health")
@limiter.limit("30/minute")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "environment": settings.environment,
        "execution_mode": settings.execution_mode,
        "capabilities": settings.capabilities,
    }


TF_TO_SECONDS = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400}


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
        if bucket not in bucketed:
            bucketed[bucket] = {
                'time': bucket,
                'open': float(candle.get('open', 0.0)),
                'high': float(candle.get('high', 0.0)),
                'low': float(candle.get('low', 0.0)),
                'close': float(candle.get('close', 0.0)),
            }
            continue
        entry = bucketed[bucket]
        entry['high'] = max(entry['high'], float(candle.get('high', entry['high'])))
        entry['low'] = min(entry['low'], float(candle.get('low', entry['low'])))
        entry['close'] = float(candle.get('close', entry['close']))
    ordered = sorted(bucketed.values(), key=lambda x: x['time'])
    return ordered


@app.get("/history/{ticker}")
async def get_history(ticker: str, tf: str = "1h", limit: int = 500) -> list[dict[str, Any]]:
    """Return historical bars, optionally resampled to the requested timeframe."""
    creds = _alpaca_credentials()
    if not creds:
        raise HTTPException(
            status_code=503,
            detail="Alpaca credentials not configured. Set ALPACA_API_KEY and ALPACA_SECRET_KEY.",
        )

    chart_data = await asyncio.to_thread(_fetch_history_chart_sync, creds[0], creds[1], ticker.upper())
    resampled = _resample_candles(chart_data, tf)
    if limit and len(resampled) > 0:
        resampled = resampled[-max(10, min(int(limit), 2000)):]
    return [
        {
            **candle,
            **candle_provenance(
                source="alpaca",
                data_time=int(candle["time"]),
                coverage=f"US equities / {tf}",
            ),
        }
        for candle in resampled
    ]


@app.get("/market/{ticker}/history")
async def get_market_history(ticker: str, tf: str = "1h", limit: int = 500) -> list[dict[str, Any]]:
    return await get_history(ticker=ticker, tf=tf, limit=limit)


def _fetch_history_chart_sync(api_key: str, secret_key: str, ticker: str) -> list[dict[str, Any]]:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(api_key, secret_key)
    end = datetime.now(timezone.utc)
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
    return chart_data


@app.websocket("/ws/trading")
async def websocket_trading(websocket: WebSocket) -> None:
    """Clients connect here for live symbol/tf subscriptions.

    Clients should send JSON messages to subscribe:
      {"action":"subscribe", "symbol":"EURUSD", "tf":"1m"}
    or to unsubscribe:
      {"action":"unsubscribe", "symbol":"EURUSD", "tf":"1m"}
    Use "*" for wildcard symbol or tf.
    
    Authentication: Pass token as query parameter ?token=JWT_TOKEN
    or as Authorization header.
    """
    # Authenticate via query parameter or header
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        return
    
    from app.auth import decode_token
    token_data = decode_token(token)
    if not token_data or token_data.exp < datetime.now(timezone.utc):
        await websocket.close(code=4001, reason="Invalid or expired token")
        return
    
    await websocket.accept()
    client = { 'ws': websocket, 'subs': set(), 'user_id': token_data.user_id }
    async with _ws_clients_lock:
        _ws_clients.append(client)
    try:
        while True:
            text = await websocket.receive_text()
            try:
                payload = json.loads(text)
                action = payload.get('action')
                if action == 'subscribe':
                    sym = (payload.get('symbol') or '*').upper()
                    tf = payload.get('tf') or '*'
                    client['subs'].add((sym, tf))
                    await websocket.send_json({'type': 'subscribed', 'symbol': sym, 'tf': tf})
                elif action == 'unsubscribe':
                    sym = (payload.get('symbol') or '*').upper()
                    tf = payload.get('tf') or '*'
                    client['subs'].discard((sym, tf))
                    await websocket.send_json({'type': 'unsubscribed', 'symbol': sym, 'tf': tf})
                elif action == 'ping':
                    await websocket.send_json({'type': 'pong'})
            except json.JSONDecodeError:
                # ignore non-JSON pings
                continue
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_clients_lock:
            if client in _ws_clients:
                _ws_clients.remove(client)
