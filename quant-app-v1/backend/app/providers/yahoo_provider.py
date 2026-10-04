"""Yahoo Finance market-data adapter backed by the ``yfinance`` module.

This is Gateway's default chart/quote provider: it needs no API key and is
already a declared dependency.  The ``yfinance`` module is loaded lazily
through the helper declared at the top of this file, so importing the
provider (and booting the API) never pays for the dependency's startup cost.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any, Optional

from app.providers.base import MarketDataProvider, ProviderMeta


def _yfinance():
    """Lazy import: load yfinance on first use, not at module import time."""
    import yfinance as yf

    return yf


def _to_epoch(value: Any) -> Optional[float]:
    """Best-effort conversion of a yfinance index/value to a UTC epoch."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    for candidate in (value,):
        ts = getattr(candidate, "timestamp", None)
        if callable(ts):
            try:
                return float(ts())
            except (ValueError, OSError, OverflowError):
                return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


class YahooFinanceProvider(MarketDataProvider):
    """Default credentials-free provider (Yahoo Finance via yfinance)."""

    def __init__(self, api_key: str = "", paper_trading: bool = True) -> None:
        # Yahoo Finance needs no credentials; api_key is accepted only so the
        # provider satisfies the uniform registry constructor signature.
        self._api_key = api_key
        self._paper_trading = paper_trading

    @property
    def name(self) -> str:
        return "Yahoo Finance"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "Yahoo Finance",
            "version": "yf-v1",
            "endpoint": "https://query1.finance.yahoo.com",
            "requires_api_key": False,
            "rate_limit_per_min": 60,
        }

    @property
    def is_configured(self) -> bool:
        return True

    async def history(
        self,
        instrument: str,
        interval: str = "1d",
        range: str = "1y",
    ) -> Optional[list[dict[str, Any]]]:
        """Fetch historical OHLCV bars from Yahoo Finance."""

        def _fetch() -> list[dict[str, Any]]:
            yf = _yfinance()
            frame = yf.Ticker(instrument.upper()).history(
                period=range, interval=interval, auto_adjust=False
            )
            if frame is None or frame.empty:
                return []
            candles: list[dict[str, Any]] = []
            for index, row in frame.iterrows():
                ts = _to_epoch(index)
                close = float(row.get("Close", 0) or 0)
                if ts is None or not math.isfinite(close) or close <= 0:
                    continue
                candles.append(
                    {
                        "time": int(ts),
                        "open": float(row.get("Open", close) or close),
                        "high": float(row.get("High", close) or close),
                        "low": float(row.get("Low", close) or close),
                        "close": close,
                        "volume": float(row.get("Volume", 0) or 0),
                    }
                )
            candles.sort(key=lambda c: c["time"])
            return candles

        return await asyncio.to_thread(_fetch)

    async def quote(self, instrument: str) -> Optional[dict[str, Any]]:
        """Last-price snapshot via yfinance ``fast_info``."""

        def _fetch() -> dict[str, Any] | None:
            yf = _yfinance()
            symbol = instrument.upper()
            fast = yf.Ticker(symbol).fast_info
            price = float(fast.last_price or 0)
            prev = float(fast.previous_close or 0)
            if not math.isfinite(price) or price <= 0:
                return None
            change = price - prev if prev > 0 else 0.0
            return {
                "symbol": symbol,
                "price": round(price, 4),
                "change": round(change, 4),
                "change_pct": round((change / prev * 100.0) if prev > 0 else 0.0, 2),
                "provider_version": "yf-v1",
            }

        return await asyncio.to_thread(_fetch)
