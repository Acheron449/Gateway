"""OpenBB Data Provider — wraps OpenBB data into Gateway's normalized models.

Phase 6 — Slice 6.1: OpenBB Data Provider
Feature-gated via ENABLE_OPENBB_DATA (default: false).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from app.models import Candle, Provenance
from app.providers.base import MarketDataProvider, ProviderMeta

logger = logging.getLogger(__name__)


@dataclass
class OpenBBConfig:
    """Configuration for OpenBB provider."""
    api_key: Optional[str] = None
    timeout: float = 15.0
    max_retries: int = 3
    retry_delay: float = 1.0
    rate_limit_per_min: int = 60


class OpenBBProvider(MarketDataProvider):
    """OpenBB-backed provider for equities, crypto, and fixed income data.

    Wraps `obb` modules to return normalized `Candle` records with provenance.
    """

    def __init__(self, config: Optional[OpenBBConfig] = None):
        self._config = config or OpenBBConfig()
        self._obb = None
        self._initialized = False
        self._rate_limit_semaphore: Optional[asyncio.Semaphore] = None

    @property
    def name(self) -> str:
        return "OpenBB"

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            name="OpenBB",
            version="openbb-v1",
            endpoint="https://github.com/OpenBB-finance/OpenBB",
            requires_api_key=False,
            rate_limit_per_min=self._config.rate_limit_per_min,
        )

    @property
    def is_configured(self) -> bool:
        return self._config is not None

    async def _init_obb(self) -> None:
        """Lazy initialization of OpenBB SDK."""
        if self._initialized:
            return

        try:
            import openbb as obb
            self._obb = obb
            self._initialized = True
            logger.info("OpenBB SDK initialized successfully")
        except ImportError as e:
            logger.error(f"OpenBB SDK not available: {e}")
            raise RuntimeError("OpenBB SDK not installed. Run 'pip install openbb'.") from e

    def _ensure_rate_limiter(self) -> asyncio.Semaphore:
        if self._rate_limit_semaphore is None:
            self._rate_limit_semaphore = asyncio.Semaphore(self._config.rate_limit_per_min)
        return self._rate_limit_semaphore

    async def _call_with_retry(self, func, *args, **kwargs) -> Any:
        """Execute OpenBB call with retry logic and rate limiting."""
        semaphore = self._ensure_rate_limiter()
        async with semaphore:
            last_error = None
            for attempt in range(self._config.max_retries):
                try:
                    result = await asyncio.to_thread(func, *args, **kwargs)
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < self._config.max_retries - 1:
                        await asyncio.sleep(self._config.retry_delay * (attempt + 1))
            raise last_error

    def _transform_equity_dataframe(self, df: pd.DataFrame, symbol: str) -> List[Candle]:
        """Transform OpenBB equity DataFrame to Gateway Candle list."""
        if df.empty:
            return []

        candles = []
        for idx, row in df.iterrows():
            ts = idx.timestamp() if hasattr(idx, 'timestamp') else idx
            candle = Candle(
                instrument=symbol.upper(),
                timeframe="1d",
                time=datetime.fromtimestamp(ts, tz=timezone.utc),
                open=float(row.get("Open", row.get("open", 0))),
                high=float(row.get("High", row.get("high", 0))),
                low=float(row.get("Low", row.get("low", 0))),
                close=float(row.get("Close", row.get("close", 0))),
                volume=float(row.get("Volume", row.get("volume", 0))),
                provenance=Provenance(
                    source="openbb",
                    provider_version="openbb-v1",
                    fetched_at=datetime.now(timezone.utc),
                    data_time=datetime.fromtimestamp(ts, tz=timezone.utc),
                    coverage="US equities / daily",
                    delay_seconds=86400,
                    entitlement="public",
                ),
            )
            candles.append(candle)
        return candles

    def _transform_crypto_dataframe(self, df: pd.DataFrame, symbol: str) -> List[Candle]:
        """Transform OpenBB crypto DataFrame to Gateway Candle list."""
        if df.empty:
            return []

        candles = []
        for idx, row in df.iterrows():
            ts = idx.timestamp() if hasattr(idx, 'timestamp') else idx
            candle = Candle(
                instrument=symbol.upper(),
                timeframe="1d",
                time=datetime.fromtimestamp(ts, tz=timezone.utc),
                open=float(row.get("Open", row.get("open", 0))),
                high=float(row.get("High", row.get("high", 0))),
                low=float(row.get("Low", row.get("low", 0))),
                close=float(row.get("Close", row.get("close", 0))),
                volume=float(row.get("Volume", row.get("volume", 0))),
                provenance=Provenance(
                    source="openbb",
                    provider_version="openbb-v1",
                    fetched_at=datetime.now(timezone.utc),
                    data_time=datetime.fromtimestamp(ts, tz=timezone.utc),
                    coverage="Crypto / daily",
                    delay_seconds=3600,
                    entitlement="public",
                ),
            )
            candles.append(candle)
        return candles

    async def history(
        self, symbol: str, interval: str = "1d", range: str = "1y"
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch historical OHLCV data from OpenBB."""
        await self._init_obb()

        try:
            if self._obb is None:
                return None

            # Determine asset class based on symbol format
            is_crypto = "-" in symbol and symbol.split("-")[1] in ("USD", "USDT", "BTC", "ETH")
            is_forex = len(symbol) == 6 and symbol[:3].isalpha() and symbol[3:].isalpha()

            if is_crypto:
                # Crypto: use obb.crypto.price.historical
                df = await self._call_with_retry(
                    self._obb.crypto.price.historical,
                    symbol=symbol.upper(),
                    interval=interval,
                    start_date=None,
                    end_date=None,
                )
                candles = self._transform_crypto_dataframe(df, symbol)
            elif is_forex:
                # Forex: use obb.forex.price.historical
                df = await self._call_with_retry(
                    self._obb.forex.price.historical,
                    symbol=symbol.upper(),
                    interval=interval,
                )
                candles = self._transform_equity_dataframe(df, symbol)
            else:
                # Equity: use obb.equity.price.historical
                df = await self._call_with_retry(
                    self._obb.equity.price.historical,
                    symbol=symbol.upper(),
                    interval=interval,
                    start_date=None,
                    end_date=None,
                )
                candles = self._transform_equity_dataframe(df, symbol)

            # Convert to dict format expected by existing API
            return [
                {
                    "time": int(c.time.timestamp()),
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "provenance": {
                        "source": c.provenance.source,
                        "provider_version": c.provenance.provider_version,
                        "fetched_at": c.provenance.fetched_at.isoformat(),
                        "data_time": c.provenance.data_time.isoformat() if c.provenance.data_time else None,
                        "coverage": c.provenance.coverage,
                        "delay_seconds": c.provenance.delay_seconds,
                        "entitlement": c.provenance.entitlement,
                    }
                }
                for c in candles
            ]

        except Exception as e:
            logger.error(f"OpenBB history fetch failed for {symbol}: {e}")
            return None

    async def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch real-time quote from OpenBB."""
        await self._init_obb()

        try:
            if self._obb is None:
                return None

            is_crypto = "-" in symbol and symbol.split("-")[1] in ("USD", "USDT", "BTC", "ETH")

            if is_crypto:
                quote = await self._call_with_retry(
                    self._obb.crypto.price.quote,
                    symbol=symbol.upper(),
                )
            else:
                quote = await self._call_with_retry(
                    self._obb.equity.price.quote,
                    symbol=symbol.upper(),
                )

            if quote is None or (hasattr(quote, 'empty') and quote.empty):
                return None

            return {
                "symbol": symbol.upper(),
                "last_price": float(quote.get("last", quote.get("close", 0))),
                "bid": float(quote.get("bid", 0)) if quote.get("bid") else None,
                "ask": float(quote.get("ask", 0)) if quote.get("ask") else None,
                "change": float(quote.get("change", 0)) if quote.get("change") else None,
                "change_pct": float(quote.get("change_pct", 0)) if quote.get("change_pct") else None,
                "provenance": {
                    "source": "openbb",
                    "provider_version": "openbb-v1",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "coverage": "Crypto / real-time" if is_crypto else "US equities / real-time",
                    "delay_seconds": 1,
                    "entitlement": "public",
                }
            }

        except Exception as e:
            logger.error(f"OpenBB quote fetch failed for {symbol}: {e}")
            return None

    async def news(self, symbol: Optional[str] = None, limit: int = 5) -> List[Any]:
        """Fetch news from OpenBB."""
        await self._init_obb()

        try:
            if self._obb is None:
                return []

            from app.models import NewsItem

            news_df = await self._call_with_retry(
                self._obb.news.world,
                limit=limit,
            )

            items = []
            for _, row in news_df.iterrows():
                items.append(NewsItem(
                    id=row.get("id", str(hash(row.get("url", "")))[:8]),
                    headline=row.get("title", ""),
                    url=row.get("url"),
                    source=row.get("source", "OpenBB"),
                    published_at=pd.to_datetime(row.get("date", datetime.now())),
                    fetched_at=datetime.now(timezone.utc),
                    categories=row.get("tags", []),
                    related_symbols=row.get("symbols", [symbol] if symbol else []),
                    sentiment_score=float(row.get("sentiment", 0.0)),
                    provider_version="openbb-v1",
                ))
            return items

        except Exception as e:
            logger.error(f"OpenBB news fetch failed: {e}")
            return []

    async def calendar(self, limit: int = 5) -> List[Any]:
        """Fetch economic calendar from OpenBB."""
        await self._init_obb()

        try:
            if self._obb is None:
                return []

            from app.models import EconomicEvent, EventImportance

            cal_df = await self._call_with_retry(
                self._obb.economy.calendar,
                limit=limit,
            )

            events = []
            for _, row in cal_df.iterrows():
                imp_map = {"low": EventImportance.LOW, "medium": EventImportance.MEDIUM, "high": EventImportance.HIGH}
                importance = imp_map.get(str(row.get("importance", "medium")).lower(), EventImportance.MEDIUM)

                events.append(EconomicEvent(
                    id=row.get("event", str(hash(row.get("title", "")))[:8]),
                    title=row.get("title", ""),
                    country=row.get("country", "US"),
                    currency=row.get("currency", "USD"),
                    importance=importance,
                    scheduled_at=pd.to_datetime(row.get("date", datetime.now())),
                    actual=float(row.get("actual", 0.0)) if row.get("actual") is not None else None,
                    forecast=float(row.get("forecast", 0.0)) if row.get("forecast") is not None else None,
                    prior=float(row.get("previous", 0.0)) if row.get("previous") is not None else None,
                    revisions=row.get("revisions", []),
                    related_symbols=row.get("related_symbols", []),
                    provider_version="openbb-v1",
                ))
            return events

        except Exception as e:
            logger.error(f"OpenBB calendar fetch failed: {e}")
            return []

    async def close(self) -> None:
        """Cleanup resources."""
        self._initialized = False
        self._obb = None