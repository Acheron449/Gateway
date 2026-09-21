"""Finnhub adapter for normalized news, calendar, and quote records."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.models import EconomicEvent, EventImportance, NewsItem
from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError


FINNHUB_BASE = "https://finnhub.io/api/v1"
FINNHUB_NEWS_ENDPOINT = "/stock/news"
FINNHUB_CALENDAR_ENDPOINT = "/calendar/economic"
FINNHUB_QUOTE_ENDPOINT = "/quote"
FINNHUB_VERSION = "finnhub-v1"
FINNHUB_RATE_LIMIT = 60


def _stable_id(prefix: str, value: str) -> str:
    natural_key = str(value or "missing").strip()
    digest = hashlib.sha256(f"{prefix}:{natural_key}".encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)):
        result = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            result = datetime.fromtimestamp(int(text), tz=timezone.utc)
        else:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    else:
        raise ValueError("unsupported timestamp")
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _importance(value: Any) -> EventImportance:
    if isinstance(value, (int, float)):
        return {1: EventImportance.LOW, 2: EventImportance.MEDIUM, 3: EventImportance.HIGH}.get(
            int(value),
            EventImportance.MEDIUM,
        )
    return {
        "low": EventImportance.LOW,
        "medium": EventImportance.MEDIUM,
        "high": EventImportance.HIGH,
    }.get(str(value).strip().lower(), EventImportance.MEDIUM)


class FinnhubProvider(MarketDataProvider):
    """Finnhub-backed read-only provider for US equities context."""

    def __init__(
        self,
        api_key: str = "",
        paper_trading: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._paper_trading = paper_trading
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        return "Finnhub"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "Finnhub",
            "version": FINNHUB_VERSION,
            "endpoint": FINNHUB_BASE,
            "requires_api_key": True,
            "rate_limit_per_min": FINNHUB_RATE_LIMIT,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {"X-Finnhub-Token": self._api_key} if self._api_key else {}

    async def news(
        self,
        symbol: str | None = None,
        limit: int = 5,
    ) -> list[NewsItem]:
        if not self.is_configured or limit <= 0 or not symbol:
            return []

        today = datetime.now(timezone.utc)
        params = {
            "symbol": symbol.upper(),
            "from": (today - timedelta(days=30)).date().isoformat(),
            "to": today.date().isoformat(),
            "limit": limit,
        }
        try:
            response = await self._http.get(
                f"{FINNHUB_BASE}{FINNHUB_NEWS_ENDPOINT}",
                params=params,
                headers=self._headers(),
            )
        except Exception as exc:
            raise ProviderUnavailableError("Finnhub news request failed") from exc
        if response.status_code != 200:
            raise ProviderUnavailableError("Finnhub news request was rejected")
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError("Finnhub news response was malformed") from exc
        articles = payload if isinstance(payload, list) else payload.get("news", []) if isinstance(payload, dict) else None
        if articles is None or not isinstance(articles, list):
            raise ProviderUnavailableError("Finnhub news response was malformed")
        fetched_at = datetime.now(timezone.utc)
        records = []
        for article in articles[:limit]:
            if not isinstance(article, dict):
                continue
            related = _as_list(article.get("related"))
            if not related and article.get("symbol"):
                related = [article["symbol"]]
            try:
                published_at = _as_datetime(article.get("datetime"))
            except Exception as exc:
                raise ProviderUnavailableError("Finnhub news response was malformed") from exc
            natural_id = article.get("id") or article.get("url") or article.get("headline") or published_at.isoformat()
            records.append(
                NewsItem(
                    id=_stable_id("finnhub-news", str(natural_id)),
                    headline=str(article.get("headline", "")),
                    url=article.get("url"),
                    source=str(article.get("source") or "Finnhub"),
                    published_at=published_at,
                    fetched_at=fetched_at,
                    categories=[str(value) for value in _as_list(article.get("categories"))],
                    related_symbols=[str(value).upper() for value in related],
                    sentiment_score=_as_float(article.get("sentiment")),
                    provider_version=FINNHUB_VERSION,
                    data_time=published_at,
                    coverage="US equities news",
                    delay_seconds=0,
                    entitlement="finnhub-free-tier",
                )
            )
        return records

    async def calendar(self, limit: int = 5) -> list[EconomicEvent]:
        if not self.is_configured or limit <= 0:
            return []

        try:
            response = await self._http.get(
                f"{FINNHUB_BASE}{FINNHUB_CALENDAR_ENDPOINT}",
                params={"limit": limit},
                headers=self._headers(),
            )
        except Exception as exc:
            raise ProviderUnavailableError("Finnhub calendar request failed") from exc
        if response.status_code != 200:
            raise ProviderUnavailableError("Finnhub calendar request was rejected")
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError("Finnhub calendar response was malformed") from exc
        events = payload if isinstance(payload, list) else payload.get("economic", []) if isinstance(payload, dict) else None
        if events is None or not isinstance(events, list):
            raise ProviderUnavailableError("Finnhub calendar response was malformed")
        fetched_at = datetime.now(timezone.utc)
        records = []
        for event in events[:limit]:
            if not isinstance(event, dict):
                continue
            try:
                scheduled = _as_datetime(event.get("timestamp"))
            except Exception as exc:
                raise ProviderUnavailableError("Finnhub calendar response was malformed") from exc
            natural_id = ":".join(
                [
                    str(event.get("event", "")),
                    str(event.get("timestamp", "")),
                    str(event.get("country", "")),
                ]
            )
            records.append(
                EconomicEvent(
                    id=_stable_id("finnhub-event", natural_id),
                    title=str(event.get("title") or event.get("event") or "Unknown economic event"),
                    country=str(event.get("country") or "US"),
                    currency=str(event.get("currency") or "USD"),
                    importance=_importance(event.get("importance")),
                    scheduled_at=scheduled,
                    actual=_as_float(event.get("actual")),
                    forecast=_as_float(event.get("estimate", event.get("forecast"))),
                    prior=_as_float(event.get("previous", event.get("prior"))),
                    revisions=[dict(value) for value in _as_list(event.get("revisions")) if isinstance(value, dict)],
                    related_symbols=[str(value).upper() for value in _as_list(event.get("related"))],
                    provider_version=FINNHUB_VERSION,
                    source="Finnhub",
                    fetched_at=fetched_at,
                    data_time=scheduled,
                    coverage="US economic calendar",
                    delay_seconds=0,
                    entitlement="finnhub-free-tier",
                )
            )
        return records

    async def quote(self, symbol: str) -> dict[str, Any] | None:
        if not self.is_configured or not symbol.strip():
            return None

        try:
            response = await self._http.get(
                f"{FINNHUB_BASE}{FINNHUB_QUOTE_ENDPOINT}",
                params={"symbol": symbol.upper()},
                headers=self._headers(),
            )
        except Exception as exc:
            raise ProviderUnavailableError("Finnhub quote request failed") from exc
        if response.status_code != 200:
            raise ProviderUnavailableError("Finnhub quote request was rejected")
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError("Finnhub quote response was malformed") from exc
        if not isinstance(payload, dict):
            raise ProviderUnavailableError("Finnhub quote response was malformed")
        try:
            last_price = _as_float(payload.get("c"))
            data_time = _as_datetime(payload["t"]) if payload.get("t") is not None else None
        except Exception as exc:
            raise ProviderUnavailableError("Finnhub quote response was malformed") from exc
        if last_price is None or not math.isfinite(last_price) or last_price <= 0:
            raise ProviderUnavailableError("Finnhub quote response did not include a valid price")
        return {
            "instrument": symbol.upper(),
            "last_price": last_price,
            "bid": None,
            "ask": None,
            "change": _as_float(payload.get("d")),
            "change_pct": _as_float(payload.get("dp")),
            "provenance": {
                "source": "Finnhub",
                "provider_version": FINNHUB_VERSION,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "data_time": data_time.isoformat() if data_time else None,
                "coverage": "US equities quote",
                "delay_seconds": 0,
                "entitlement": "finnhub-free-tier",
            },
        }

    async def health_check(self) -> dict[str, Any]:
        result = await super().health_check()
        if not self.is_configured:
            return result
        try:
            response = await self._http.get(
                f"{FINNHUB_BASE}{FINNHUB_QUOTE_ENDPOINT}",
                params={"symbol": "AAPL"},
                headers=self._headers(),
                timeout=5.0,
            )
            result.update(
                {
                    "status": "healthy" if response.status_code == 200 else "degraded",
                    "latency_ms": round(response.elapsed.total_seconds() * 1000, 2) if response.elapsed else None,
                }
            )
        except Exception:
            result.update({"status": "degraded"})
        return result

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None
