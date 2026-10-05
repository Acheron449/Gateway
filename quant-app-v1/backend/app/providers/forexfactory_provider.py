"""ForexFactory economic-calendar provider (direct scrape of /calendar).

ForexFactory has no public API; this adapter fetches
https://www.forexfactory.com/calendar with browser-like headers and parses the
server-rendered table. The site sits behind Cloudflare bot protection, so the
fetch can be challenged (HTTP 403) from some networks — that surfaces as an
honest ``ProviderUnavailableError`` and the calendar endpoint falls back to the
next source (the sanctioned way to get ForexFactory data is the JBlanked
ForexFactory feed).

Timestamps: date comes from the row's day cell, time from the row's time cell
("8:30am" / "All Day") and both are interpreted in the site's display timezone
(fixed UTC+2 by default, override with ``FOREXFACTORY_TZ_OFFSET_HOURS``).
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone as dt_timezone

from app.models import EconomicEvent, EventImportance
from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError
from app.providers.calendar_scrape import (
    cell_text,
    cell_with_class,
    fetch_html,
    parse_table_rows,
    to_float,
    tz_from_env,
)

_CALENDAR_URL = "https://www.forexfactory.com/calendar"
_DATE_RE = re.compile(r"([A-Z][a-z]{2}\s+\d{1,2})")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*(?:am|pm))", re.IGNORECASE)

_CURRENCY_COUNTRY = {
    "USD": "US", "EUR": "EU", "GBP": "GB", "JPY": "JP", "CAD": "CA",
    "AUD": "AU", "CHF": "CH", "NZD": "NZ", "CNY": "CN", "HKD": "HK",
    "SGD": "SG", "NOK": "NO", "SEK": "SE", "DKK": "DK", "PLN": "PL",
    "TRY": "TR", "ZAR": "ZA", "MXN": "MX", "BRL": "BR", "INR": "IN",
}


def _impact_from_marks(marks: list[dict]) -> EventImportance:
    joined = " ".join(
        f"{mark.get('class', '')} {mark.get('title', '')}".lower() for mark in marks
    )
    if "impact-red" in joined or "high" in joined:
        return EventImportance.HIGH
    if "impact-yel" in joined or "impact-yellow" in joined or "medium" in joined:
        return EventImportance.MEDIUM
    return EventImportance.LOW


def _parse_date_text(text: str, now: datetime) -> datetime | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    label = re.sub(r"\s+", " ", match.group(1)).strip()
    for year in (now.year, now.year + 1, now.year - 1):
        try:
            return datetime.strptime(f"{label} {year}", "%b %d %Y")
        except ValueError:
            continue
    return None


def parse_forexfactory_calendar(html: str) -> list[EconomicEvent]:
    tz = tz_from_env("FOREXFACTORY_TZ_OFFSET_HOURS", 2)
    now = datetime.now(dt_timezone.utc)
    events: list[EconomicEvent] = []
    current_day: datetime | None = None

    for row in parse_table_rows(html):
        row_class = str(row.attrs.get("class", ""))
        if "calendar__row--day-breaker" in row_class:
            text = " ".join(cell_text(cell) for cell in row.cells)
            current_day = _parse_date_text(text, now) or current_day
            continue

        date_cell = cell_with_class(row, "calendar__date")
        if date_cell is not None:
            parsed = _parse_date_text(cell_text(date_cell), now)
            if parsed is not None:
                current_day = parsed

        time_cell = cell_with_class(row, "calendar__time")
        currency_cell = cell_with_class(row, "calendar__currency")
        event_cell = cell_with_class(row, "calendar__event")
        if time_cell is None or event_cell is None:
            continue
        title = cell_text(event_cell)
        if not title:
            continue

        time_text = cell_text(time_cell)
        time_match = _TIME_RE.search(time_text)
        if current_day is None:
            continue
        if time_match:
            clock = datetime.strptime(re.sub(r"\s+", "", time_match.group(1)).lower(), "%I:%M%p").time()
        elif "all day" in time_text.lower():
            clock = datetime.min.time()
        else:
            clock = datetime.min.time()

        naive = datetime.combine(current_day.date(), clock)
        scheduled = naive.replace(tzinfo=tz).astimezone(dt_timezone.utc)

        currency = (cell_text(currency_cell) or "USD").strip().upper()[:4]
        impact_cell = cell_with_class(row, "calendar__impact")
        marks = impact_cell["marks"] if impact_cell else []
        impact = _impact_from_marks(marks)

        actual_cell = cell_with_class(row, "calendar__actual")
        forecast_cell = cell_with_class(row, "calendar__forecast")
        previous_cell = cell_with_class(row, "calendar__previous")
        event_id_attr = str(row.attrs.get("data-event-id") or "")
        natural = f"{event_id_attr}|{title}|{naive.isoformat()}|{currency}"
        event_id = "ff-" + hashlib.sha1(natural.encode("utf-8")).hexdigest()[:16]

        events.append(
            EconomicEvent(
                id=event_id,
                title=title,
                country=_CURRENCY_COUNTRY.get(currency, currency),
                currency=currency,
                importance=impact,
                scheduled_at=scheduled,
                actual=to_float(cell_text(actual_cell)) if actual_cell else None,
                forecast=to_float(cell_text(forecast_cell)) if forecast_cell else None,
                prior=to_float(cell_text(previous_cell)) if previous_cell else None,
                related_symbols=[],
                provider_version="forexfactory-calendar-v1",
                source="ForexFactory",
                data_time=scheduled,
                coverage="ForexFactory economic calendar",
                entitlement="public-scrape",
            )
        )

    events.sort(key=lambda e: e.scheduled_at)
    return events


class ForexFactoryProvider(MarketDataProvider):
    """Direct ForexFactory calendar scrape — no API key, best-effort on bot walls."""

    def __init__(self, api_key: str = "") -> None:  # api_key unused; uniform signature
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "ForexFactory"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "ForexFactory",
            "version": "forexfactory-calendar-v1",
            "endpoint": _CALENDAR_URL,
            "requires_api_key": False,
            "rate_limit_per_min": 6,
        }

    @property
    def is_configured(self) -> bool:
        return True

    async def calendar(self, limit: int = 5) -> list[EconomicEvent]:
        if limit <= 0:
            return []
        html = await fetch_html(_CALENDAR_URL)
        events = parse_forexfactory_calendar(html)
        if not events:
            raise ProviderUnavailableError(
                "ForexFactory page parsed to zero events (markup change or interstitial page)"
            )
        return events[: max(1, min(int(limit), 500))]
