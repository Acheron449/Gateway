from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, List

import pandas as pd

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
        """Establishes connection to the Time-Series Database."""
        print("Connecting to TimescaleDB instance...")
        # Add connection pooling/pooling logic here
        await asyncio.sleep(1) # Simulate connection delay
        print("Database connection established.")
        
    async def stream_live_market_data(self, tick_handler) -> None:
        """
        Simulates listening to live market data feeds.
        tick_handler is a callback function to pass new data to the Orchestrator.
        """
        print("Listening for live market ticks...")
        # In a real system, this runs forever/until cancelled
        while self.is_live:
            # Simulating receiving a new tick every second
            await asyncio.sleep(1) 
            new_tick = TickData(timestamp=time.time(), price=150.0 + (time.time()%1), volume=100)
            # Pass the cleaned tick to the handler
            await tick_handler(new_tick)
         
    def fetch_historical_data(self, start_time: float, end_time: float) -> List[TickData]:
        """
        Retrieves a batch of clean, time-series data for backtesting.
        """
        print(f"Fetching data from DB for [{start_time} to {end_time})...")
        # This is where the connection to TimescaleDB occurs to retrieve batch data
        return [] # Placeholder for fetched data

    def start_live_feeds(self):
        self.is_live = True
        print("Data Ingestion is LIVE.")


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
