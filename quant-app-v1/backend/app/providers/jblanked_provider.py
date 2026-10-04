"""JBlanked news/calendar API provider.

Official API documented at https://www.jblanked.com/news/api/docs/calendar/ —
free access to economic-calendar events aggregated from ForexFactory, MQL5 and
FxStreet. Authentication uses an ``Api-Key`` header; the key comes from the
Providers settings page (BYOK) or the ``JBLANKED_API_KEY`` environment variable.

Requests are rate-limited upstream to 1/second, so responses are cached in
memory for 60s. Timestamps in the API are naive local strings; the docs'
worked example (Core CPI at 15:30 for an 08:30 ET release) implies a UTC+2
render, overridable via ``JBLANKED_TZ_OFFSET_HOURS``.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from app.models import EconomicEvent, EventImportance
from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError
from app.providers.calendar_scrape import parse_naive, to_float, tz_from_env

_BASE = "https://www.jblanked.com/news/api"
_FEED = os.getenv("JBLANKED_FEED", "forex-factory").strip().strip("/") or "forex-factory"
_CACHE_TTL_SECONDS = 60.0
_cache: dict[str, tuple[float, list[EconomicEvent]]] = {}

_CURRENCY_COUNTRY = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "CAD": "CA",
    "AUD": "AU", "CHF": "CH", "NZD": "NZ", "CNY": "CN", "HKD": "HK",
    "SGD": "SG", "NOK": "NO", "SEK": "SE", "DKK": "DK", "PLN": "PL",
    "TRY": "TR", "ZAR": "ZA", "MXN": "MX", "BRL": "BR", "INR": "IN",
    "KRW": "KR", "TWD": "TW", "THB": "TH", "IDR": "ID", "PHP": "PH",
    "MYR": "MY", "SAR": "SA", "AED": "AE", "ILS": "IL", "HUF": "HU",
    "CZK": "CZ", "RON": "RO", "BGN": "BG", "ARS": "AR", "CLP": "CL",
    "COP": "CO", "PEN": "PE", "EGP": "EG", "NGN": "NG", "KES": "KE",
}

_IMPORTANCE = {
    "high": EventImportance.HIGH,
    "medium": EventImportance.MEDIUM,
    "med": EventImportance.MEDIUM,
    "low": EventImportance.LOW,
    "none": EventImportance.LOW,
    "": EventImportance.LOW,
}


def _httpx():
    """Lazy import: httpx loads on first use, not at module import time."""
    import httpx

    return httpx


def _number(value: Any) -> Optional[float]:
    return to_float(value)


def _to_event(item: dict[str, Any], tz) -> Optional[EconomicEvent]:
    name = str(item.get("Name") or "").strip()
    date_raw = str(item.get("Date") or "").strip()
    if not name or not date_raw:
        return None
    scheduled = parse_naive(
        date_raw,
        ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y-%m-%d %H:%M"),
        tz,
    )
    if scheduled is None or scheduled.year < 2000:
        return None

    currency = str(item.get("Currency") or "USD").upper()[:4]
    impact = str(item.get("Impact") or "low").strip().lower()
    natural = f"{name}|{date_raw}|{currency}"
    event_id = "jb-" + hashlib.sha1(natural.encode("utf-8")).hexdigest()[:16]

    feed = _FEED.replace("-", " ").title()
    return EconomicEvent(
        id=event_id,
        title=name,
        country=_CURRENCY_COUNTRY.get(currency, currency),
        currency=currency or "USD",
        importance=_IMPORTANCE.get(impact, EventImportance.LOW),
        scheduled_at=scheduled,
        actual=_number(item.get("Actual")),
        forecast=_number(item.get("Forecast")),
        prior=_number(item.get("Previous")),
        related_symbols=[],
        provider_version="jblanked-v1",
        source="JBlanked",
        data_time=scheduled,
        coverage=f"{feed} via JBlanked",
        entitlement="jblanked-api",
    )


class JBlankedProvider(MarketDataProvider):
    """Official JBlanked calendar API — needs a (free) API key."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = (api_key or "").strip()

    @property
    def name(self) -> str:
        return "JBlanked"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "JBlanked",
            "version": "jblanked-v1",
            "endpoint": _BASE,
            "requires_api_key": True,
            "rate_limit_per_min": 60,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def calendar(self, limit: int = 5) -> list[EconomicEvent]:
        if not self._api_key or limit <= 0:
            return []

        cache_key = f"{_FEED}:{limit}"
        cached = _cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]

        tz = tz_from_env("JBLANKED_TZ_OFFSET_HOURS", 2)
        url = f"{_BASE}/{_FEED}/calendar/week/"
        httpx = _httpx()
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Api-Key {self._api_key}",
                    },
                )
        except Exception as exc:
            raise ProviderUnavailableError(f"JBlanked request failed: {exc}") from exc

        if response.status_code == 401:
            raise ProviderUnavailableError(
                "JBlanked rejected the API key (HTTP 401); regenerate it from your JBlanked profile",
                status_code=401,
            )
        if response.status_code == 429:
            raise ProviderUnavailableError(
                "JBlanked rate limit reached (HTTP 429); one request per second is allowed",
                status_code=429,
            )
        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"JBlanked returned HTTP {response.status_code}",
                status_code=response.status_code,
            )

        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError("JBlanked response was malformed") from exc

        if isinstance(payload, dict):
            payload = payload.get("data") or payload.get("events") or payload.get("calendar") or []
        if not isinstance(payload, list):
            raise ProviderUnavailableError("JBlanked response was malformed")

        events: list[EconomicEvent] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            event = _to_event(item, tz)
            if event is not None:
                events.append(event)

        events.sort(key=lambda e: e.scheduled_at)
        events = events[: max(1, min(int(limit), 500))]
        _cache[cache_key] = (now, events)
        return events
