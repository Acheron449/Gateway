from __future__ import annotations

import asyncio
import os
import random
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pandas_ta as ta
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from loguru import logger

from app.api.v1.analysis import router as analysis_router
from app.api.v1.stocks import router as stocks_router
from app.services.market_data import _alpaca_credentials, _stock_feed


# Bridge between Alpaca (or synth feed) and WebSocket broadcast.
data_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
_ws_clients_lock = asyncio.Lock()
_ws_clients: list[WebSocket] = []

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

    async def synthetic_feeder():
        """Dev fallback when Alpaca credentials are unset."""
        buff: deque[dict[str, Any]] = deque(maxlen=30)
        base = 100.0
        while True:
            await asyncio.sleep(1.0)
            base += random.uniform(-0.15, 0.15)
            buff.append({"close": base})
            rsi_val = 0.0
            if len(buff) >= RSI_PERIOD:
                rsi_series = ta.rsi(pd.DataFrame(list(buff))["close"], length=RSI_PERIOD)
                last = rsi_series.iloc[-1]
                if pd.notna(last):
                    rsi_val = float(last)

            await data_queue.put(
                {
                    "symbol": ws_symbol,
                    "price": round(base, 4),
                    "rsi": round(rsi_val, 2),
                }
            )

    async def dispatch_queue():
        """Drain the queue once and broadcast to every connected `/ws/trading` client."""
        while True:
            msg = await data_queue.get()
            async with _ws_clients_lock:
                targets = list(_ws_clients)
            for ws in targets:
                try:
                    await ws.send_json(msg)
                except Exception as exc:
                    logger.debug("Dropping websocket client after send failure: {}", exc)
                    async with _ws_clients_lock:
                        if ws in _ws_clients:
                            _ws_clients.remove(ws)

    tasks: list[asyncio.Task] = []
    tasks.append(asyncio.create_task(dispatch_queue(), name="ws-dispatch-queue"))

    if creds:
        tasks.append(asyncio.create_task(alpaca_streamer(), name="alpaca-queue-feed"))
    else:
        logger.warning(
            "Alpaca credentials not set — using synthetic RSI feed for /ws/trading. "
            "Set ALPACA_API_KEY and ALPACA_SECRET_KEY."
        )
        tasks.append(asyncio.create_task(synthetic_feeder(), name="synthetic-queue-feed"))

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


app = FastAPI(title="Quant App API", version="0.1.0", lifespan=lifespan)

app.include_router(stocks_router)
app.include_router(analysis_router)


@app.get("/")
def home() -> dict:
    return {"status": "Quant Engine Running"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/history/{ticker}")
async def get_history(ticker: str) -> list[dict[str, Any]]:
    """Last ~30 days of 1-hour bars for TradingView-style charts (Alpaca historical API)."""
    creds = _alpaca_credentials()
    if not creds:
        raise HTTPException(
            status_code=503,
            detail="Alpaca credentials not configured. Set ALPACA_API_KEY and ALPACA_SECRET_KEY.",
        )

    chart_data = await asyncio.to_thread(_fetch_history_chart_sync, creds[0], creds[1], ticker.upper())
    return chart_data


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
    """Clients connect here for live.symbol / price / rsi pushed from the Alpaca-backed queue."""
    await websocket.accept()
    async with _ws_clients_lock:
        _ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        async with _ws_clients_lock:
            if websocket in _ws_clients:
                _ws_clients.remove(websocket)
