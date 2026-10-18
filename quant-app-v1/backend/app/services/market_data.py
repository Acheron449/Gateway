from __future__ import annotations

import asyncio
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional

import pandas as pd

from app.services.provenance import candle_provenance
from app.services.as_of import normalize_as_of


def _yf():
    """Lazy import declared at the top of the file: yfinance loads on first
    use (quote/OHLCV fetches) instead of at module-import time."""
    import yfinance as yf

    return yf


# --- Data Models ---

@dataclass
class TickData:
    """Represents a single market data point."""
    timestamp: float # Unix timestamp or similar high-precision float
    price: float
    volume: int
    # Other relevant fields like bid/ask size, etc.

@dataclass
class SignalPayload:
    """Data package received from external providers (e.g., News/Technical Analysis)."""
    timestamp: float
    sentiment_score: float
    pattern_features: List[Any]  # Signals from impact_model.py.

class MarketDataIngestor:
    """
    Centralized service responsible for fetching, cleaning, synchronizing, and providing
    market data streams to consumers (Backtester, Orchestrator).
    """
    def __init__(self, db_connection_string: str):
        self.db_connection = db_connection_string
        self.is_live = False
        print("MarketDataIngestor initialized. Ready to connect to Time-Series DB.")

    async def connect_to_db(self):
        """Fail closed instead of pretending a time-series database is connected."""
        raise RuntimeError("Historical market data is unavailable; configure a provider")

    async def stream_live_market_data(self, tick_handler) -> None:
        """Fail closed instead of emitting synthetic ticks."""
        del tick_handler
        raise RuntimeError("Live market data is unavailable; configure a provider")

    def fetch_historical_data(self, start_time: float, end_time: float) -> List[TickData]:
        """
        Retrieves a batch of clean, time-series data for backtesting.
        """
        del start_time, end_time
        raise RuntimeError("Historical market data is unavailable; configure a provider")

    def start_live_feeds(self):
        raise RuntimeError("Live market data is unavailable; configure a provider")


def _alpaca_credentials() -> tuple[str, str] | None:
    """Return configured Alpaca credentials without exposing them to callers."""
    key = os.getenv("ALPACA_API_KEY") or os.getenv("ALPACA_API_KEY_ID")
    secret = os.getenv("ALPACA_SECRET_KEY")
    return (key, secret) if key and secret else None


# --- Last-price source for paper trading (fill simulator + order ticket) ---

_price_cache: dict[str, tuple[float, float]] = {}  # symbol -> (price, cached_at)
# Aggressive default: fills and risk checks want the freshest quote possible.
# GATEWAY_PRICE_TTL tunes it per deployment (seconds).
_PRICE_TTL_SECONDS = float(os.getenv("GATEWAY_PRICE_TTL", "10"))
_DEFAULT_HALF_SPREAD_BPS = float(os.getenv("PAPER_HALF_SPREAD_BPS", "5"))


def _fetch_last_price_sync(symbol: str) -> float | None:
    """Fetch the real last trade price via yfinance (credentials-free)."""
    try:
        yf = _yf()

        fast = yf.Ticker(symbol.upper()).fast_info
        price = float(fast.last_price or 0)
    except Exception:
        return None
    return price if math.isfinite(price) and price > 0 else None


def get_quote_triplet_sync(symbol: str) -> tuple[float, float, float] | None:
    """Return (bid, ask, last) for paper fills and risk checks.

    The last price is a real quote from yfinance with a short TTL cache;
    bid/ask are a small configurable spread around it — the paper-fill
    model approximates the NBBO around the real last trade.
    """
    sym = symbol.strip().upper()
    if not sym:
        return None

    now = time.time()
    cached = _price_cache.get(sym)
    price: float | None = None
    if cached is not None and now - cached[1] < _PRICE_TTL_SECONDS:
        price = cached[0]
    else:
        price = _fetch_last_price_sync(sym)
        if price is not None:
            _price_cache[sym] = (price, now)

    if price is None:
        return None

    half = price * (_DEFAULT_HALF_SPREAD_BPS / 10_000.0)
    return (price - half, price + half, price)


def _stock_feed() -> str:
    return "sip" if os.getenv("ALPACA_STOCK_FEED", "").upper() == "SIP" else "iex"


@dataclass
class OhlcvResult:
    """OHLCV data with provenance metadata."""
    dataframe: pd.DataFrame
    provenance: dict[str, Any]


async def fetch_ohlcv(
    ticker: str,
    limit: int = 500,
    *,
    as_of: datetime | None = None,
) -> OhlcvResult:
    """Fetch a normalized OHLCV frame for analysis and forecasting routes.

    yfinance is already a Gateway dependency and provides a credentials-free
    historical fallback; providers that require credentials remain responsible
    for real-time streaming in ``api.main``.
    """
    def _fetch() -> pd.DataFrame:
        yf = _yf()

        cutoff = normalize_as_of(as_of)
        result = yf.Ticker(ticker.upper()).history(
            period="2y",
            interval="1d",
            end=cutoff.replace(tzinfo=None) if cutoff else None,
            auto_adjust=False,
        )
        if result.empty:
            raise ValueError(f"No historical OHLCV data found for '{ticker.upper()}'")
        result = result.rename(columns={"Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"})
        if cutoff:
            if result.index.tz is None:
                raise ValueError(
                    f"Historical OHLCV data for '{ticker.upper()}' has no timezone-aware timestamps"
                )
            result = result.loc[result.index.tz_convert("UTC") <= cutoff]
        if cutoff and result.empty:
            raise ValueError(f"No historical OHLCV data found for '{ticker.upper()}' at or before as_of")
        return result[["Open", "High", "Low", "Close", "Volume"]].tail(max(2, min(limit, 2000))).copy()

    df = await asyncio.to_thread(_fetch)
    provenance = candle_provenance(
        source="yfinance",
        data_time=int(df.index[-1].timestamp()) if len(df) > 0 else int(time.time()),
        coverage=f"US equities / daily",
        delay_seconds=86400,  # daily data has ~1 day delay
    )
    return OhlcvResult(dataframe=df, provenance=provenance)
