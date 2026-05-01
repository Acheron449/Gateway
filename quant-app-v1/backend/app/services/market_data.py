from __future__ import annotations

import asyncio
import os
import queue
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
from loguru import logger


def _alpaca_credentials() -> tuple[str, str] | None:
    key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if key and secret:
        return key, secret
    return None


def _stock_feed():
    from alpaca.data.enums import DataFeed

    return DataFeed.SIP if os.getenv("ALPACA_STOCK_FEED", "").upper() == "SIP" else DataFeed.IEX


def _partition_stream_symbols(tickers: list[str]) -> tuple[list[str], list[str]]:
    stocks: list[str] = []
    crypto: list[str] = []
    for raw in tickers:
        s = raw.strip()
        if not s:
            continue
        if "/" in s:
            crypto.append(s)
        else:
            stocks.append(s.upper())
    return stocks, crypto


def _bar_to_dict(data: Any) -> dict:
    if isinstance(data, dict):
        sym = data.get("S") or data.get("symbol")
        return {
            "symbol": sym,
            "price": float(data.get("c") or data.get("close") or 0),
            "open": float(data.get("o") or data.get("open") or 0),
            "high": float(data.get("h") or data.get("high") or 0),
            "low": float(data.get("l") or data.get("low") or 0),
            "volume": float(data.get("v") or data.get("volume") or 0),
            "timestamp": data.get("t") or data.get("timestamp"),
        }
    return {
        "symbol": data.symbol,
        "price": float(data.close),
        "open": float(data.open),
        "high": float(data.high),
        "low": float(data.low),
        "volume": float(data.volume),
        "timestamp": getattr(data, "timestamp", None),
    }


def _timeframe_from_string(timeframe: str):
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    tf = timeframe.strip().lower()
    if tf in ("1d", "d", "day", "1day"):
        return TimeFrame.Day
    if tf in ("1h", "h", "hour", "1hour"):
        return TimeFrame.Hour
    if tf in ("15m", "15min"):
        return TimeFrame(15, TimeFrameUnit.Minute)
    if tf in ("5m", "5min"):
        return TimeFrame(5, TimeFrameUnit.Minute)
    if tf in ("1m", "m", "minute", "1min"):
        return TimeFrame.Minute
    return TimeFrame.Day


def _synthetic_ohlcv(limit: int) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    index = [end - timedelta(days=offset) for offset in range(limit)][::-1]

    base = 100.0
    returns = np.random.normal(loc=0.0008, scale=0.02, size=limit)
    close = base * np.cumprod(1 + returns)
    open_ = np.insert(close[:-1], 0, close[0]) * (1 + np.random.normal(0, 0.002, size=limit))
    high = np.maximum(open_, close) * (1 + np.abs(np.random.normal(0, 0.003, size=limit)))
    low = np.minimum(open_, close) * (1 - np.abs(np.random.normal(0, 0.003, size=limit)))
    volume = np.random.randint(500_000, 5_000_000, size=limit)

    df = pd.DataFrame(
        {
            "Timestamp": index,
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        }
    )
    df["volatility"] = df["Close"].pct_change().rolling(20, min_periods=5).std().fillna(0.0)
    return df


def _normalize_alpaca_bars_df(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.reset_index()
    rename = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "timestamp": "Timestamp",
    }
    out = out.rename(columns={k: v for k, v in rename.items() if k in out.columns})

    if "Timestamp" not in out.columns:
        for col in out.columns:
            if str(col).lower() == "timestamp":
                out = out.rename(columns={col: "Timestamp"})
                break

    if "Timestamp" not in out.columns:
        raise ValueError("Alpaca bars DataFrame missing a timestamp column after reset_index")

    if "symbol" in out.columns:
        out = out.drop(columns=["symbol"])

    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in out.columns:
            lower = col.lower()
            if lower in out.columns:
                out = out.rename(columns={lower: col})

    out = out.sort_values("Timestamp").tail(limit)
    out["volatility"] = out["Close"].pct_change().rolling(20, min_periods=5).std().fillna(0.0)
    return out.reset_index(drop=True)


def _fetch_alpaca_bars_sync(
    ticker: str,
    timeframe: str,
    limit: int,
    api_key: str,
    api_secret: str,
) -> pd.DataFrame:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest

    client = StockHistoricalDataClient(api_key, api_secret)
    tf = _timeframe_from_string(timeframe)
    end = datetime.now(timezone.utc)
    request = StockBarsRequest(
        symbol_or_symbols=ticker.upper(),
        timeframe=tf,
        end=end,
        limit=limit,
    )
    bars = client.get_stock_bars(request)
    df = bars.df
    return _normalize_alpaca_bars_df(df, limit)


async def fetch_ohlcv(ticker: str, timeframe: str = "1d", limit: int = 120) -> pd.DataFrame:
    creds = _alpaca_credentials()
    if creds:
        api_key, api_secret = creds
        try:
            return await asyncio.to_thread(
                _fetch_alpaca_bars_sync,
                ticker,
                timeframe,
                limit,
                api_key,
                api_secret,
            )
        except Exception as exc:
            logger.warning(
                "Alpaca fetch failed for {} ({}); using synthetic data. {}",
                ticker,
                timeframe,
                exc,
            )

    return _synthetic_ohlcv(limit)


def start_market_stream(tickers: list[str] | None = None) -> None:
    """
    Blocking entry point: connects to Alpaca live minute bars (stocks via StockDataStream,
    crypto pairs like BTC/USD via CryptoDataStream in a background thread).

    Set ALPACA_API_KEY + ALPACA_SECRET_KEY (or APCA_API_KEY_ID + APCA_API_SECRET_KEY).
    Optional: ALPACA_STOCK_FEED=SIP for SIP (subscription required).
    """
    tickers = tickers or ["AAPL", "TSLA"]
    creds = _alpaca_credentials()
    if not creds:
        logger.error("Missing Alpaca credentials. Set ALPACA_API_KEY and ALPACA_SECRET_KEY.")
        return

    api_key, secret_key = creds
    stocks, crypto = _partition_stream_symbols(tickers)

    async def handle_bar(data) -> None:
        payload = _bar_to_dict(data)
        logger.info(
            "Ticker: {} | Close: {} | Vol: {}",
            payload["symbol"],
            payload["price"],
            payload.get("volume"),
        )

    def run_crypto_stream() -> None:
        from alpaca.data.live import CryptoDataStream

        stream = CryptoDataStream(api_key, secret_key, raw_data=False)
        stream.subscribe_bars(handle_bar, *crypto)
        logger.success("Crypto stream started. Monitoring: {}", crypto)
        stream.run()

    crypto_thread: Optional[threading.Thread] = None
    if crypto:
        crypto_thread = threading.Thread(target=run_crypto_stream, daemon=True)
        crypto_thread.start()

    if stocks:
        from alpaca.data.live import StockDataStream

        stream = StockDataStream(api_key, secret_key, raw_data=False, feed=_stock_feed())
        stream.subscribe_bars(handle_bar, *stocks)
        logger.success("Stock stream connection. Monitoring: {}", stocks)
        stream.run()
    elif crypto and crypto_thread is not None:
        crypto_thread.join()
    else:
        logger.warning("No symbols to subscribe after filtering: {}", tickers)


async def start_websocket_stream(ticker_list: list[str]):
    """
    Async generator of bar payloads for wiring into a FastAPI WebSocket.

    Uses Alpaca live minute bars when credentials are set; otherwise yields synthetic ticks.
    """
    tickers = ticker_list or ["AAPL"]
    creds = _alpaca_credentials()
    stocks, crypto = _partition_stream_symbols(tickers)

    if creds and (stocks or crypto):
        from alpaca.data.live import CryptoDataStream, StockDataStream

        out_q: queue.SimpleQueue[dict] = queue.SimpleQueue()
        streams: dict[str, Any | None] = {"stock": None, "crypto": None}

        async def enqueue_bar(data) -> None:
            out_q.put(_bar_to_dict(data))

        def run_stock() -> None:
            stream = StockDataStream(creds[0], creds[1], raw_data=False, feed=_stock_feed())
            streams["stock"] = stream
            stream.subscribe_bars(enqueue_bar, *stocks)
            stream.run()

        def run_crypto() -> None:
            stream = CryptoDataStream(creds[0], creds[1], raw_data=False)
            streams["crypto"] = stream
            stream.subscribe_bars(enqueue_bar, *crypto)
            stream.run()

        threads: list[threading.Thread] = []
        if stocks:
            threads.append(threading.Thread(target=run_stock, daemon=True))
        if crypto:
            threads.append(threading.Thread(target=run_crypto, daemon=True))
        for t in threads:
            t.start()

        try:
            while True:
                yield await asyncio.to_thread(out_q.get)
        finally:
            for stream in streams.values():
                if stream is not None:
                    try:
                        stream.stop()
                    except Exception as exc:
                        logger.debug("Alpaca stream stop: {}", exc)
        return

    demo_symbols = stocks + crypto if (stocks or crypto) else ["AAPL"]
    base = {s: 100.0 for s in demo_symbols}
    while True:
        for sym, price in list(base.items()):
            jitter = float(np.random.normal(0, 0.05))
            base[sym] = max(1.0, price + jitter)
            yield {"symbol": sym, "price": base[sym], "volume": 0.0}
        await asyncio.sleep(1.0)


if __name__ == "__main__":
    start_market_stream()
