"""Economic-calendar API providers.

Two adapters:

1. ``EconomicCalendarApiProvider`` — the default/base calendar feed, wrapping
   the self-hostable <https://github.com/andrevlima/economic-calendar-api>
   JSON endpoint (a simple array of ``{economy, impact, data, name, actual,
   forecast, previous}`` records sourced from investing.com). Point it at your
   instance with ``ECONOMIC_CALENDAR_API_URL`` (optionally
   ``ECONOMIC_CALENDAR_TZ_OFFSET_HOURS`` for the display timezone).

2. ``FmpCalendarProvider`` — the Financial Modeling Prep economics calendar
   (https://site.financialmodelingprep.com/developer/docs/stable/economics-calendar),
   enabled with ``FMP_API_KEY`` (or ``FINANCIALMODELINGPREP_API_KEY``).

Other calendar sources (JBlanked, Bloomberg, Finnhub) layer their events on
top of this base in the ``/news/calendar`` endpoint.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Optional

from app.models import EconomicEvent, EventImportance
from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError
from app.providers.calendar_scrape import parse_naive, to_float, tz_from_env


_CURRENCY_COUNTRY = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "CAD": "CA",
    "AUD": "AU", "CHF": "CH", "NZD": "NZ", "CNY": "CN", "HKD": "HK",
    "SGD": "SG", "NOK": "NO", "SEK": "SE", "DKK": "DK", "PLN": "PL",
    "TRY": "TR", "ZAR": "ZA", "MXN": "MX", "BRL": "BR", "INR": "IN",
}

_COUNTRY_CURRENCY = {country: cur for cur, country in _CURRENCY_COUNTRY.items()}


def _httpx():
    import httpx

    return httpx


def _stable_id(prefix: str, natural: str) -> str:
    return prefix + hashlib.sha1(natural.encode("utf-8")).hexdigest()[:16]


def _impact_int(value: Any) -> EventImportance:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 0
    if n >= 3:
        return EventImportance.HIGH
    if n == 2:
        return EventImportance.MEDIUM
    return EventImportance.LOW


def _impact_text(value: Any) -> EventImportance:
    text = str(value or "").strip().lower()
    if text.startswith("high"):
        return EventImportance.HIGH
    if text.startswith("med"):
        return EventImportance.MEDIUM
    return EventImportance.LOW


# ---------------------------------------------------------------------------
# Default base feed: andrevlima/economic-calendar-api
# ---------------------------------------------------------------------------


class EconomicCalendarApiProvider(MarketDataProvider):
    """Self-hostable economic-calendar JSON endpoint (the default feed)."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key  # unused; uniform factory signature

    @property
    def name(self) -> str:
        return "EconomicCalendar"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "EconomicCalendar",
            "version": "econ-cal-api-v1",
            "endpoint": _base_url() or "https://github.com/andrevlima/economic-calendar-api",
            "requires_api_key": False,
            "rate_limit_per_min": 30,
        }

    @property
    def is_configured(self) -> bool:
        return bool(_base_url())

    async def calendar(self, limit: int = 5) -> list[EconomicEvent]:
        url = _base_url()
        if not url or limit <= 0:
            return []
        tz = tz_from_env("ECONOMIC_CALENDAR_TZ_OFFSET_HOURS", 0)
        httpx = _httpx()
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(url, headers={"Accept": "application/json"})
        except Exception as exc:
            raise ProviderUnavailableError(f"Economic-calendar API request failed: {exc}") from exc
        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"Economic-calendar API returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError("Economic-calendar API response was malformed") from exc
        if isinstance(payload, dict):
            payload = payload.get("events") or payload.get("data") or []
        if not isinstance(payload, list):
            raise ProviderUnavailableError("Economic-calendar API response was malformed")

        events: list[EconomicEvent] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            date_raw = str(item.get("data") or item.get("date") or "").strip()
            if not name or not date_raw:
                continue
            scheduled = parse_naive(
                date_raw,
                ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"),
                tz,
            )
            if scheduled is None:
                continue
            currency = str(item.get("economy") or item.get("currency") or "USD").strip().upper()[:3]
            natural = f"{scheduled.isoformat()}|{name}|{currency}"
            events.append(
                EconomicEvent(
                    id=_stable_id("ecapi-", natural),
                    title=name,
                    country=_CURRENCY_COUNTRY.get(currency, "US"),
                    currency=currency,
                    importance=_impact_int(item.get("impact")),
                    scheduled_at=scheduled,
                    actual=to_float(item.get("actual")),
                    forecast=to_float(item.get("forecast")),
                    prior=to_float(item.get("previous")),
                    related_symbols=[],
                    provider_version="econ-cal-api-v1",
                    source="EconomicCalendar",
                    data_time=scheduled,
                    coverage="Economic calendar (economic-calendar-api)",
                    entitlement="public-feed",
                )
            )
        events.sort(key=lambda e: e.scheduled_at)
        return events[: max(1, min(int(limit), 500))]


def _base_url() -> str:
    return os.getenv("ECONOMIC_CALENDAR_API_URL", "").strip().rstrip("/")


# ---------------------------------------------------------------------------
# Financial Modeling Prep economics calendar (item 13)
# ---------------------------------------------------------------------------

_FMP_BASE = "https://financialmodelingprep.com/api/v3/economic-calendar"


def _fmp_key() -> str:
    return (
        os.getenv("FMP_API_KEY", "").strip()
        or os.getenv("FINANCIALMODELINGPREP_API_KEY", "").strip()
    )


class FmpCalendarProvider(MarketDataProvider):
    """Financial Modeling Prep economics calendar (API key required)."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key  # unused; key comes from FMP_API_KEY env

    @property
    def name(self) -> str:
        return "FinancialModelingPrep"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "FinancialModelingPrep",
            "version": "fmp-calendar-v1",
            "endpoint": _FMP_BASE,
            "requires_api_key": True,
            "rate_limit_per_min": 60,
        }

    @property
    def is_configured(self) -> bool:
        return bool(_fmp_key())

    async def calendar(self, limit: int = 5) -> list[EconomicEvent]:
        key = _fmp_key()
        if not key or limit <= 0:
            return []
        tz = tz_from_env("FMP_TZ_OFFSET_HOURS", 0)
        httpx = _httpx()
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(_FMP_BASE, params={"apikey": key})
        except Exception as exc:
            raise ProviderUnavailableError(f"FMP calendar request failed: {exc}") from exc
        if response.status_code in (401, 402):
            raise ProviderUnavailableError(
                "FMP rejected the API key (HTTP 401/402)", status_code=response.status_code
            )
        if response.status_code != 200:
            raise ProviderUnavailableError(
                f"FMP calendar returned HTTP {response.status_code}", status_code=response.status_code
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError("FMP calendar response was malformed") from exc
        if not isinstance(payload, list):
            raise ProviderUnavailableError("FMP calendar response was malformed")

        events: list[EconomicEvent] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            title = str(item.get("event") or item.get("title") or "").strip()
            date_raw = str(item.get("date") or "").strip()
            if not title or not date_raw:
                continue
            scheduled = parse_naive(
                date_raw,
                ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"),
                tz,
            )
            if scheduled is None:
                continue
            country = str(item.get("country") or "US").strip().upper()
            currency = str(item.get("currency") or "").strip().upper()[:3] or _COUNTRY_CURRENCY.get(country, "USD")
            natural = f"{scheduled.isoformat()}|{title}|{currency}"
            events.append(
                EconomicEvent(
                    id=_stable_id("fmp-", natural),
                    title=title,
                    country=country,
                    currency=currency,
                    importance=_impact_text(item.get("impact")),
                    scheduled_at=scheduled,
                    actual=to_float(item.get("actual")),
                    forecast=to_float(item.get("estimate", item.get("forecast"))),
                    prior=to_float(item.get("previous", item.get("prior"))),
                    related_symbols=[],
                    provider_version="fmp-calendar-v1",
                    source="FinancialModelingPrep",
                    data_time=scheduled,
                    coverage="FMP economic calendar",
                    entitlement="fmp-api",
                )
            )
        events.sort(key=lambda e: e.scheduled_at)
        return events[: max(1, min(int(limit), 500))]


__all__ = ["EconomicCalendarApiProvider", "FmpCalendarProvider"]
