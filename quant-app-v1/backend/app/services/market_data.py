from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, List, Optional

import pandas as pd

from app.config import get_settings
from app.providers.openbb_provider import OpenBBProvider, OpenBBConfig
from app.services.provenance import candle_provenance


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


def _stock_feed() -> str:
    return "sip" if os.getenv("ALPACA_STOCK_FEED", "").upper() == "SIP" else "iex"


@dataclass
class OhlcvResult:
    """OHLCV data with provenance metadata."""
    dataframe: pd.DataFrame
    provenance: dict[str, Any]


async def fetch_ohlcv(ticker: str, limit: int = 500) -> OhlcvResult:
    """Fetch a normalized OHLCV frame for analysis and forecasting routes.

    yfinance is already a Gateway dependency and provides a credentials-free
    historical fallback; providers that require credentials remain responsible
    for real-time streaming in ``api.main``.
    """
    def _fetch() -> pd.DataFrame:
        import yfinance as yf

        result = yf.Ticker(ticker.upper()).history(period="2y", interval="1d", auto_adjust=False)
        if result.empty:
            raise ValueError(f"No historical OHLCV data found for '{ticker.upper()}'")
        result = result.rename(columns={"Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"})
        return result[["Open", "High", "Low", "Close", "Volume"]].tail(max(2, min(limit, 2000))).copy()

    df = await asyncio.to_thread(_fetch)
    provenance = candle_provenance(
        source="yfinance",
        data_time=int(df.index[-1].timestamp()) if len(df) > 0 else int(time.time()),
        coverage=f"US equities / daily",
        delay_seconds=86400,  # daily data has ~1 day delay
    )
    return OhlcvResult(dataframe=df, provenance=provenance)


# --- OpenBB Data Ingestion (Phase 6 - Slice 6.3) ---

class OpenBBIngestor:
    """OpenBB data ingestor for the quant engine pipeline.

    Feeds OpenBB historical data into indicators, backtester, and risk engine.
    Feature-gated via ENABLE_OPENBB_DATA.
    """

    def __init__(self):
        self._provider: Optional[OpenBBProvider] = None
        self._initialized = False

    def _get_provider(self) -> Optional[OpenBBProvider]:
        settings = get_settings()
        if not settings.enable_openbb_data:
            return None

        if self._provider is None:
            self._provider = OpenBBProvider(OpenBBConfig())
        return self._provider

    async def fetch_history(
        self,
        symbol: str,
        interval: str = "1d",
        period: str = "1y",
    ) -> Optional[pd.DataFrame]:
        """Fetch historical OHLCV data from OpenBB as pandas DataFrame."""
        provider = self._get_provider()
        if provider is None:
            return None

        try:
            data = await provider.history(symbol=symbol, interval=interval, range=period)
            if data is None or len(data) == 0:
                return None

            df = pd.DataFrame(data)
            df["timestamp"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("timestamp", inplace=True)
            df = df.rename(columns={
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            })
            return df[["Open", "High", "Low", "Close", "Volume"]]
        except Exception as e:
            print(f"OpenBB fetch failed for {symbol}: {e}")
            return None

    async def fetch_multiple(
        self,
        symbols: List[str],
        interval: str = "1d",
        period: str = "1y",
    ) -> Dict[str, pd.DataFrame]:
        """Fetch historical data for multiple symbols."""
        results = {}
        for symbol in symbols:
            df = await self.fetch_history(symbol, interval, period)
            if df is not None:
                results[symbol] = df
        return results

    def get_provenance(self, symbol: str) -> dict[str, Any]:
        """Get provenance metadata for OpenBB data."""
        return candle_provenance(
            source="openbb",
            data_time=int(time.time()),
            coverage=f"US equities / {symbol}",
            delay_seconds=86400,
        )


async def fetch_ohlcv_openbb(ticker: str, limit: int = 500) -> OhlcvResult:
    """Fetch OHLCV from OpenBB with provenance (alternative to yfinance)."""
    ingestor = OpenBBIngestor()
    df = await ingestor.fetch_history(ticker, interval="1d", period="2y")
    if df is None or df.empty:
        # Fallback to yfinance
        return await fetch_ohlcv(ticker, limit)

    provenance = ingestor.get_provenance(ticker)
    return OhlcvResult(dataframe=df.tail(limit), provenance=provenance)
