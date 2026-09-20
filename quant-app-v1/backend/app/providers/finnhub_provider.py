"""Finnhub provider implementation for news, calendar, and quotes."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.models import EconomicEvent, EventImportance, NewsItem
from app.providers.base import MarketDataProvider, ProviderMeta


FINNHUB_BASE = "https://finnhub.io/api/v1"
FINNHUB_NEWS_ENDPOINT = "/stock/news"
FINNHUB_CALENDAR_ENDPOINT = "/calendar/economic"
FINNHUB_QUOTE_ENDPOINT = "/quote"

_FINNHUB_RATE_LIMIT = 60  # free tier


class FinnhubProvider(MarketDataProvider):
    """Finnhub-backed provider — free tier 60 req/min, US equities + calendar."""

    def __init__(self, api_key: str, paper_trading: bool = True):
        self._api_key = api_key
        self._paper_trading = paper_trading
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "Finnhub"

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            name="Finnhub",
            version="finnhub-v1",
            endpoint=FINNHUB_BASE,
            requires_api_key=True,
            rate_limit_per_min=_FINNHUB_RATE_LIMIT,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    def _headers(self) -> Dict[str, str]:
        return {"X-Finnhub-Token": self._api_key} if self._api_key else {}

    async def news(
        self, symbol: Optional[str] = None, limit: int = 5
    ) -> List[NewsItem]:
        if not self.is_configured:
            return []

        symbol_param = symbol or ""
        url = f"{FINNHUB_BASE}/stock/news?symbol={symbol_param}&limit={limit}"

        try:
            resp = await self._http.get(url, headers=self._headers())
            if resp.status_code != 200:
                return []
            data = resp.json()

            items: List[NewsItem] = []
            for article in data.get("news", [])[:limit]:
                items.append(
                    NewsItem(
                        id=article.get("id", hashlib.md5(article.get("url", "").encode()).hexdigest()[:8]),
                        headline=article.get("headline", ""),
                        url=article.get("url"),
                        source=article.get("source", "Finnhub"),
                        published_at=datetime.fromtimestamp(
                            article.get("datetime", int(time.time())), tz=timezone.utc
                        ),
                        fetched_at=datetime.now(timezone.utc),
                        categories=article.get("categories", []),
                        related_symbols=article.get("related_symbol", []),
                        sentiment_score=float(article.get("sentiment", 0.0)),
                        provider_version="finnhub-v1",
                    )
                )
            return items

        except Exception:
            return []

    async def calendar(self, limit: int = 5) -> List[EconomicEvent]:
        if not self.is_configured:
            return []

        url = f"{FINNHUB_BASE}{FINNHUB_CALENDAR_ENDPOINT}?limit={limit}"

        try:
            resp = await self._http.get(url, headers=self._headers())
            if resp.status_code != 200:
                return []
            data = resp.json()

            events: List[EconomicEvent] = []
            for ev in data.get("economic", [])[:limit]:
                imp_map = {
                    "low": EventImportance.LOW,
                    "medium": EventImportance.MEDIUM,
                    "high": EventImportance.HIGH,
                }
                importance = imp_map.get(ev.get("importance", "medium"), EventImportance.MEDIUM)

                events.append(
                    EconomicEvent(
                        id=ev.get("event", hashlib.md5(ev.get("title", "").encode()).hexdigest()[:8]),
                        title=ev.get("title", ""),
                        country=ev.get("country", "US"),
                        currency=ev.get("currency", "USD"),
                        importance=importance,
                        scheduled_at=datetime.fromtimestamp(
                            ev.get("timestamp", int(time.time())), tz=timezone.utc
                        ),
                        actual=float(ev.get("actual", 0.0)) if ev.get("actual") is not None else None,
                        forecast=float(ev.get("forecast", 0.0)) if ev.get("forecast") is not None else None,
                        prior=float(ev.get("prior", 0.0)) if ev.get("prior") is not None else None,
                        revisions=ev.get("revisions", []),
                        related_symbols=ev.get("related", []),
                        provider_version="finnhub-v1",
                    )
                )
            return events

        except Exception:
            return []

    async def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.is_configured:
            return None

        url = f"{FINNHUB_BASE}{FINNHUB_QUOTE_ENDPOINT}?symbol={symbol}"

        try:
            resp = await self._http.get(url, headers=self._headers())
            if resp.status_code != 200:
                return None
            data = resp.json()

            return {
                "symbol": symbol.upper(),
                "last_price": data.get("c"),
                "change": data.get("d"),
                "change_pct": data.get("dp"),
                "high": data.get("h"),
                "low": data.get("l"),
                "open": data.get("o"),
                "previous_close": data.get("pc"),
                "timestamp": data.get("t"),
                "source": "Finnhub",
                "provider_version": "finnhub-v1",
            }
        except Exception:
            return None

    async def health_check(self) -> Dict[str, Any]:
        base = await super().health_check()
        if self.is_configured:
            try:
                resp = await self._http.get(
                    f"{FINNHUB_BASE}{FINNHUB_QUOTE_ENDPOINT}?symbol=AAPL",
                    headers=self._headers(),
                    timeout=5.0,
                )
                base["status"] = "healthy" if resp.status_code == 200 else "degraded"
                base["latency_ms"] = resp.elapsed.total_seconds() * 1000 if resp.elapsed else None
            except Exception as e:
                base["status"] = "degraded"
                base["error"] = str(e)
        return base

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None