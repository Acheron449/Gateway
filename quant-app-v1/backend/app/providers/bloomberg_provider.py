"""Bloomberg economic-calendar provider.

Bloomberg's calendar page (https://www.bloomberg.com/markets/economic-calendar)
is fetchable, but the events render from an embedded Investing.com widget
iframe (``econcal.forexprostools.com``). This provider fetches the Bloomberg
page, discovers the widget URL, then fetches and parses the widget.

Two widget generations are parsed (verified against archived snapshots):
1. The classic div-based widget — ``<li class="item">`` rows with
   ``event_timestamp`` (UTC), ``<time datetime>`` (displayed local time),
   ``flagCur`` currency, ``sentiment`` impact and act/fcst/prev values.
2. A table-based fallback with ``data-event-datetime`` rows.

The widget sits behind Cloudflare bot protection, so server-side requests can
be challenged (HTTP 403) from some networks — that surfaces as an honest
``ProviderUnavailableError`` and the calendar endpoint falls back to the next
source instead of failing silently.

Displayed ``<time datetime>`` values are naive local strings rendered in the
widget's display timezone (observed default UTC-5/Eastern; override with
``BLOOMBERG_TZ_OFFSET_HOURS``).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone as dt_timezone
from html.parser import HTMLParser
from typing import Optional

from app.models import EconomicEvent, EventImportance
from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError
from app.providers.calendar_scrape import (
    absolute,
    cell_text,
    cell_with_class,
    fetch_html,
    parse_naive,
    parse_table_rows,
    to_float,
    tz_from_env,
)

_BLOOMBERG_URL = "https://www.bloomberg.com/markets/economic-calendar"
_IFRAME_RE = re.compile(r"<iframe[^>]+src=\"([^\"]+)\"", re.IGNORECASE)
_DATETIME_ATTR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}")
_LABEL_RE = re.compile(r"^\s*(?:Act|Fcst|Prev|Forecast|Previous|Actual)\s*:\s*", re.IGNORECASE)
_CURRENCY_RE = re.compile(r"\b([A-Z]{3})\b")

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
    if "red" in joined or "high" in joined:
        return EventImportance.HIGH
    if "yellow" in joined or "medium" in joined or "moderate" in joined:
        return EventImportance.MEDIUM
    return EventImportance.LOW


def _impact_from_title(title: str) -> EventImportance:
    lowered = title.lower()
    if "high" in lowered:
        return EventImportance.HIGH
    if "moderate" in lowered or "medium" in lowered:
        return EventImportance.MEDIUM
    return EventImportance.LOW


def _event_title(cell: dict) -> str:
    for mark in cell.get("marks", []):
        if mark.get("tag") == "a" and mark.get("title"):
            text = str(mark["title"]).strip()
            if text:
                return text
    return cell_text(cell)


def _extract_currency(text: str) -> str:
    match = _CURRENCY_RE.search(text.upper())
    return match.group(1) if match else "USD"


def _build_event(
    *,
    event_id: str,
    title: str,
    scheduled: datetime,
    currency: str,
    impact: EventImportance,
    actual: Optional[float],
    forecast: Optional[float],
    prior: Optional[float],
) -> EconomicEvent:
    return EconomicEvent(
        id=event_id,
        title=title,
        country=_CURRENCY_COUNTRY.get(currency, currency),
        currency=currency,
        importance=impact,
        scheduled_at=scheduled,
        actual=actual,
        forecast=forecast,
        prior=prior,
        related_symbols=[],
        provider_version="bloomberg-calendar-v1",
        source="Bloomberg",
        data_time=scheduled,
        coverage="Bloomberg economic calendar (Investing.com widget)",
        entitlement="public-scrape",
    )


def _stable_id(prefix: str, natural: str) -> str:
    return prefix + hashlib.sha1(natural.encode("utf-8")).hexdigest()[:16]


class _WidgetParser(HTMLParser):
    """Parse the classic div-based Investing/forexprostools calendar widget."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[EconomicEvent] = []
        self._skip = 0
        self._in_item = 0
        self._item: Optional[dict] = None
        self._slot_stack: list[str] = []
        self._text_targets: dict[str, list[str]] = {}

    def _slot(self) -> Optional[str]:
        return self._slot_stack[-1] if self._slot_stack else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = {key: (value or "") for key, value in attrs}
        if tag in ("script", "style"):
            self._skip += 1
            return

        if tag == "button" and self._item is None:
            element_id = attr_map.get("id", "")
            if element_id.startswith("eventRowId_") or "calLine" in attr_map.get("class", ""):
                self._item = {
                    "key": element_id or "",
                    "timestamp": attr_map.get("event_timestamp", ""),
                    "time_dt": "",
                    "sentiment": attr_map.get("aria-label", ""),
                    "currency": "",
                    "title": "",
                    "actual": "",
                    "forecast": "",
                    "previous": "",
                }
                self._in_item = 1
            return

        if self._item is None:
            return
        if tag == "button":
            self._in_item += 1
            return

        classes = attr_map.get("class", "")
        if tag == "time":
            self._item["time_dt"] = attr_map.get("datetime", "")
            self._slot_stack.append("time_dt" if "time" in classes else "_ignored")
        elif tag == "div":
            element_id = attr_map.get("id", "")
            if "flagCur" in classes:
                self._slot_stack.append("currency")
            elif "sentiment" in classes:
                title = attr_map.get("title", "")
                if title:
                    self._item["sentiment"] = title
                self._slot_stack.append("_ignored")
            elif "event" in classes.split():
                self._slot_stack.append("title")
            elif element_id.startswith("eventActual_"):
                self._slot_stack.append("actual")
            elif element_id.startswith("eventForecast_"):
                self._slot_stack.append("forecast")
            elif element_id.startswith("eventPrevious_"):
                self._slot_stack.append("previous")
            else:
                self._slot_stack.append("_ignored")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
            return
        if tag == "button" and self._item is not None:
            self._in_item -= 1
            if self._in_item <= 0:
                self._finalize()
            return
        if self._item is None or not self._slot_stack:
            return
        if tag in ("div", "time", "span"):
            # pop the most recent slot opened by a div/time (spans don't open slots)
            if tag == "span":
                return
            self._slot_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._skip or self._item is None:
            return
        slot = self._slot()
        if slot and slot != "_ignored" and slot != "time_dt":
            self._item[slot] += data

    def _finalize(self) -> None:
        item = self._item
        self._item = None
        self._slot_stack.clear()
        if item is None:
            return
        title = re.sub(r"\s+", " ", item["title"]).strip()
        if not title:
            return

        scheduled: Optional[datetime] = None
        timestamp = item["timestamp"].strip()
        if timestamp:
            try:
                parsed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                if parsed.year >= 2000:
                    scheduled = parsed.replace(tzinfo=dt_timezone.utc)
            except ValueError:
                scheduled = None
        if scheduled is None and item["time_dt"]:
            tz = tz_from_env("BLOOMBERG_TZ_OFFSET_HOURS", -5)
            scheduled = parse_naive(item["time_dt"], ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"), tz)
        if scheduled is None:
            return

        currency = _extract_currency(item["currency"]) or "USD"
        impact = _impact_from_title(item["sentiment"])
        natural = f"widget|{item['key']}|{scheduled.isoformat()}|{title}|{currency}"

        self.events.append(
            _build_event(
                event_id=_stable_id("bbg-", natural),
                title=title,
                scheduled=scheduled,
                currency=currency,
                impact=impact,
                actual=to_float(_LABEL_RE.sub("", item["actual"])),
                forecast=to_float(_LABEL_RE.sub("", item["forecast"])),
                prior=to_float(_LABEL_RE.sub("", item["previous"])),
            )
        )


def _parse_widget_divs(html: str) -> list[EconomicEvent]:
    parser = _WidgetParser()
    parser.feed(html)
    return parser.events


def parse_investing_calendar(html: str) -> list[EconomicEvent]:
    events: list[EconomicEvent] = []

    # Generation 2: table rows with data-event-datetime.
    for row in parse_table_rows(html):
        event_dt = str(row.attrs.get("data-event-datetime") or "").strip()
        if not event_dt or not _DATETIME_ATTR_RE.match(event_dt):
            continue
        event_cell = cell_with_class(row, "event")
        if event_cell is None:
            continue
        title = _event_title(event_cell)
        if not title:
            continue

        scheduled = None
        try:
            parsed = datetime.strptime(event_dt.replace("T", " "), "%Y-%m-%d %H:%M:%S")
            if parsed.year >= 2000:
                scheduled = parsed.replace(tzinfo=tz_from_env("BLOOMBERG_TZ_OFFSET_HOURS", -5)).astimezone(
                    dt_timezone.utc
                )
        except ValueError:
            scheduled = None
        if scheduled is None:
            continue

        currency_cell = cell_with_class(row, "flagCur") or cell_with_class(row, "currency")
        currency = _extract_currency(cell_text(currency_cell)) if currency_cell else "USD"
        sentiment_cell = (
            cell_with_class(row, "sentiment")
            or cell_with_class(row, "sentimentText")
            or cell_with_class(row, "impact")
        )
        marks = sentiment_cell["marks"] if sentiment_cell else []
        impact = _impact_from_marks(marks)
        actual_cell = cell_with_class(row, "actual")
        forecast_cell = cell_with_class(row, "forecast")
        previous_cell = cell_with_class(row, "previous")
        row_id = str(row.attrs.get("id") or row.attrs.get("data-event-id") or "")
        natural = f"table|{row_id}|{scheduled.isoformat()}|{title}|{currency}"

        events.append(
            _build_event(
                event_id=_stable_id("bbg-", natural),
                title=title,
                scheduled=scheduled,
                currency=currency,
                impact=impact,
                actual=to_float(cell_text(actual_cell)) if actual_cell else None,
                forecast=to_float(cell_text(forecast_cell)) if forecast_cell else None,
                prior=to_float(cell_text(previous_cell)) if previous_cell else None,
            )
        )

    if not events:
        # Generation 1: classic div-based widget.
        events = _parse_widget_divs(html)

    events.sort(key=lambda e: e.scheduled_at)
    return events


class BloombergProvider(MarketDataProvider):
    """Bloomberg calendar page + its embedded Investing.com widget."""

    def __init__(self, api_key: str = "") -> None:  # api_key unused; uniform signature
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "Bloomberg"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "Bloomberg",
            "version": "bloomberg-calendar-v1",
            "endpoint": _BLOOMBERG_URL,
            "requires_api_key": False,
            "rate_limit_per_min": 6,
        }

    @property
    def is_configured(self) -> bool:
        return True

    async def calendar(self, limit: int = 5) -> list[EconomicEvent]:
        if limit <= 0:
            return []

        page = await fetch_html(_BLOOMBERG_URL, referer="https://www.google.com/")
        match = _IFRAME_RE.search(page)
        if match is None:
            fallback = re.search(r"https?://[^\s\"']*econcal[^\s\"']*", page)
            if fallback is None:
                raise ProviderUnavailableError(
                    "Bloomberg calendar page did not embed the calendar widget iframe"
                )
            widget_url = fallback.group(0)
        else:
            widget_url = match.group(1)

        widget_url = absolute(widget_url, _BLOOMBERG_URL)
        widget_html = await fetch_html(widget_url, referer=_BLOOMBERG_URL)
        events = parse_investing_calendar(widget_html)
        if not events:
            raise ProviderUnavailableError(
                "Bloomberg calendar widget parsed to zero events (markup change or interstitial page)"
            )
        return events[: max(1, min(int(limit), 500))]
