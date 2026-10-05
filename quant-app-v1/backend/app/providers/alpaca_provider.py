"""Alpaca market data provider — implements the canonical Provider interface.

Phase 2 — Slice 2.1: Provider Adapter Layer
Read-only market data (history, quotes, news, calendar) via Alpaca Data API.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.models import Candle, EconomicEvent, EventImportance, Instrument, NewsItem, Quote
from app.providers.base import MarketDataProvider, ProviderMeta
from app.models import provenance_now


ALPACA_DATA_BASE = "https://data.alpaca.markets"
ALPACA_NEWS_ENDPOINT = "/v1beta1/news"
ALPACA_CALENDAR_ENDPOINT = "/v1beta1/calendar"
ALPACA_QUOTE_ENDPOINT = "/v2/stocks/quotes/latest"
ALPACA_BARS_ENDPOINT = "/v2/stocks/bars"
ALPACA_SYMBOLS_ENDPOINT = "/v2/stocks/symbols"


class AlpacaProvider(MarketDataProvider):
    """Alpaca Data API provider for US equities market data.

    Requires ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.
    Uses the SIP feed when ALPACA_STOCK_FEED=SIP, otherwise IEX.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        feed: str = "iex",
    ):
        self._api_key = api_key or os.getenv("ALPACA_API_KEY") or os.getenv("ALPACA_API_KEY_ID")
        self._api_secret = api_secret or os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
        self._feed = feed
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "Alpaca"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "Alpaca",
            "version": "alpaca-data-v2",
            "endpoint": ALPACA_DATA_BASE,
            "requires_api_key": True,
            "rate_limit_per_min": 200,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_secret)

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={
                    "APCA-API-KEY-ID": self._api_key or "",
                    "APCA-API-SECRET-KEY": self._api_secret or "",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # --- Catalogue ---

    async def catalogue(self) -> list[Instrument]:
        if not self.is_configured:
            return []

        try:
            params = {"status": "active", "asset_class": "us_equity", "limit": 1000}
            resp = await self._http.get(f"{ALPACA_DATA_BASE}{ALPACA_SYMBOLS_ENDPOINT}", params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()
            instruments = []
            for sym in data.get("symbols", []):
                instruments.append(Instrument(
                    symbol=sym.get("symbol", ""),
                    name=sym.get("name", ""),
                    exchange=sym.get("exchange", "NASDAQ"),
                    currency=sym.get("currency", "USD"),
                    asset_class="equity",
                    provenance=provenance_now(
                        source="alpaca",
                        provider_version="alpaca-data-v2",
                        coverage="US equities / active symbols",
                    ),
                ))
            return instruments
        except Exception:
            return []

    # --- History ---

    async def history(
        self,
        instrument: str,
        interval: str = "1d",
        range: str = "1y",
    ) -> list[dict[str, Any]] | None:
        if not self.is_configured:
            return None

        try:
            # Map interval to Alpaca timeframe
            timeframe_map = {
                "1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min",
                "1h": "1Hour", "4h": "4Hour", "1d": "1Day", "1w": "1Week",
            }
            timeframe = timeframe_map.get(interval, "1Day")

            # Map range to start/end
            end = datetime.now(timezone.utc)
            range_map = {
                "1d": "1 day ago", "5d": "5 days ago", "1mo": "1 month ago",
                "3mo": "3 months ago", "6mo": "6 months ago", "1y": "1 year ago",
                "2y": "2 years ago", "5y": "5 years ago", "max": "10 years ago",
            }
            start_str = range_map.get(range, "1 year ago")

            params = {
                "symbols": instrument.upper(),
                "timeframe": timeframe,
                "feed": self._feed,
                "start": start_str,
                "end": end.isoformat().replace("+00:00", "Z"),
                "limit": 10000,
            }

            resp = await self._http.get(f"{ALPACA_DATA_BASE}{ALPACA_BARS_ENDPOINT}", params=params)
            if resp.status_code != 200:
                return None

            data = resp.json()
            bars = data.get("bars", {}).get(instrument.upper(), [])
            if not bars:
                return None

            candles = []
            for bar in bars:
                candles.append({
                    "instrument": instrument.upper(),
                    "timeframe": interval,
                    "time": bar["t"],
                    "open": bar["o"],
                    "high": bar["h"],
                    "low": bar["l"],
                    "close": bar["c"],
                    "volume": bar.get("v"),
                    "trades": bar.get("n"),
                    "provenance": provenance_now(
                        source="alpaca",
                        provider_version="alpaca-data-v2",
                        coverage=f"US equities / {interval}",
                        delay_seconds=15 * 60 if self._feed == "iex" else 0,
                        data_time=datetime.fromisoformat(bar["t"].replace("Z", "+00:00")),
                    ).model_dump(),
                })
            return candles
        except Exception:
            return None

    # --- Quote ---

    async def quote(self, instrument: str) -> dict[str, Any] | None:
        if not self.is_configured:
            return None

        try:
            params = {"symbols": instrument.upper(), "feed": self._feed}
            resp = await self._http.get(f"{ALPACA_DATA_BASE}{ALPACA_QUOTE_ENDPOINT}", params=params)
            if resp.status_code != 200:
                return None

            data = resp.json()
            quote_data = data.get("quotes", {}).get(instrument.upper())
            if not quote_data:
                return None

            return {
                "instrument": instrument.upper(),
                "last_price": quote_data.get("ap") or quote_data.get("bp"),
                "bid": quote_data.get("bp"),
                "ask": quote_data.get("ap"),
                "bid_size": quote_data.get("bs"),
                "ask_size": quote_data.get("as"),
                "provenance": provenance_now(
                    source="alpaca",
                    provider_version="alpaca-data-v2",
                    coverage="US equities / real-time",
                    delay_seconds=15 * 60 if self._feed == "iex" else 0,
                ).model_dump(),
            }
        except Exception:
            return None

    # --- News ---

    async def news(
        self,
        symbol: str | None = None,
        limit: int = 5,
    ) -> list[NewsItem]:
        if not self.is_configured:
            return []

        try:
            params = {"limit": limit}
            if symbol:
                params["symbols"] = symbol.upper()

            resp = await self._http.get(f"{ALPACA_DATA_BASE}{ALPACA_NEWS_ENDPOINT}", params=params)
            if resp.status_code != 200:
                return []

            data = resp.json()
            items = []
            for article in data.get("news", [])[:limit]:
                items.append(NewsItem(
                    id=article.get("id", ""),
                    headline=article.get("headline", ""),
                    url=article.get("url"),
                    source=article.get("source", "Alpaca"),
                    published_at=datetime.fromisoformat(article.get("created_at", "").replace("Z", "+00:00")),
                    fetched_at=datetime.now(timezone.utc),
                    categories=article.get("symbols", []),
                    related_symbols=article.get("symbols", []),
                    sentiment_score=None,
                    provider_version="alpaca-data-v2",
                    coverage="US equities / news",
                ))
            return items
        except Exception:
            return []

    # --- Calendar ---

    async def calendar(self, limit: int = 5) -> list[EconomicEvent]:
        if not self.is_configured:
            return []

        try:
            params = {"limit": limit}
            resp = await self._http.get(f"{ALPACA_DATA_BASE}{ALPACA_CALENDAR_ENDPOINT}", params=params)
            if resp.status_code != 200:
                return []

            data = resp.json()
            events = []
            for ev in data.get("calendar", [])[:limit]:
                imp_map = {"low": EventImportance.LOW, "medium": EventImportance.MEDIUM, "high": EventImportance.HIGH}
                importance = imp_map.get(str(ev.get("impact", "medium")).lower(), EventImportance.MEDIUM)

                events.append(EconomicEvent(
                    id=ev.get("event", ""),
                    title=ev.get("event", ""),
                    country=ev.get("country", "US"),
                    currency=ev.get("currency", "USD"),
                    importance=importance,
                    scheduled_at=datetime.fromisoformat(ev.get("date", "").replace("Z", "+00:00")),
                    actual=float(ev.get("actual", 0.0)) if ev.get("actual") is not None else None,
                    forecast=float(ev.get("forecast", 0.0)) if ev.get("forecast") is not None else None,
                    prior=float(ev.get("previous", 0.0)) if ev.get("previous") is not None else None,
                    revisions=[],
                    related_symbols=[],
                    provider_version="alpaca-data-v2",
                    source="alpaca",
                    fetched_at=datetime.now(timezone.utc),
                    coverage="US economic calendar",
                ))
            return events
        except Exception:
            return []


# Re-export for registry
__all__ = ["AlpacaProvider"]