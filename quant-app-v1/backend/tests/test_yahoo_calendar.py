"""Yahoo Finance economic-calendar normalization and failure regressions."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.providers.base import ProviderUnavailableError
from app.providers import yahoo_provider
from app.providers.yahoo_provider import YahooFinanceProvider
from app.services import calendar_service


def _calendar_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            {
                "Event Time": "2026-10-13T12:30:00+00:00",
                "Region": "United States",
                "Actual": float("nan"),
                "Expected": 2.1,
                "Last": 1.9,
                "Revised": float("nan"),
            },
            {
                "Event Time": "2026-10-13",
                "Region": "Unknown Region",
                "Actual": 5.0,
                "Expected": None,
                "Last": None,
                "Revised": None,
            },
        ],
        index=pd.Index(["Consumer Price Index", "Date-only release"], name="Event"),
    )
    return frame


def test_yahoo_calendar_normalizes_utc_and_finite_values_with_stable_id(monkeypatch):
    monkeypatch.setattr(
        yahoo_provider,
        "_yfinance",
        lambda: SimpleNamespace(Calendars=lambda: SimpleNamespace(
            get_economic_events_calendar=lambda **kwargs: _calendar_frame()
        )),
    )
    provider = YahooFinanceProvider()

    first = asyncio.run(provider.calendar(limit=5))
    second = asyncio.run(provider.calendar(limit=5))

    assert len(first) == 1  # date-only timestamps are not assigned a fabricated release time
    event = first[0]
    assert event.title == "Consumer Price Index"
    assert event.country == "US"
    assert event.currency == "USD"
    assert event.scheduled_at == datetime(2026, 10, 13, 12, 30, tzinfo=timezone.utc)
    assert event.actual is None
    assert event.forecast == 2.1
    assert event.prior == 1.9
    assert event.revisions == []
    assert event.id == second[0].id
    assert event.provider_version == "yf-calendar-v1"
    assert event.source == "Yahoo Finance"


def test_yahoo_calendar_unknown_region_does_not_guess_currency(monkeypatch):
    frame = _calendar_frame().iloc[[0]].copy()
    frame.index = pd.Index(["Unknown region event"], name="Event")
    frame.loc[:, "Region"] = "Atlantis"
    monkeypatch.setattr(
        yahoo_provider,
        "_yfinance",
        lambda: SimpleNamespace(Calendars=lambda: SimpleNamespace(
            get_economic_events_calendar=lambda **kwargs: frame
        )),
    )

    event = asyncio.run(YahooFinanceProvider().calendar())[0]
    assert event.country == "Atlantis"
    assert event.currency == ""


def test_yahoo_calendar_returns_empty_frame_without_events(monkeypatch):
    monkeypatch.setattr(
        yahoo_provider,
        "_yfinance",
        lambda: SimpleNamespace(Calendars=lambda: SimpleNamespace(
            get_economic_events_calendar=lambda **kwargs: pd.DataFrame()
        )),
    )
    assert asyncio.run(YahooFinanceProvider().calendar()) == []


def test_yahoo_calendar_missing_api_raises_provider_unavailable(monkeypatch):
    monkeypatch.setattr(yahoo_provider, "_yfinance", lambda: SimpleNamespace())
    with pytest.raises(ProviderUnavailableError, match="calendar API is unavailable"):
        asyncio.run(YahooFinanceProvider().calendar())


def test_yahoo_calendar_upstream_exception_is_provider_unavailable(monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("upstream timeout")

    monkeypatch.setattr(
        yahoo_provider,
        "_yfinance",
        lambda: SimpleNamespace(Calendars=lambda: SimpleNamespace(
            get_economic_events_calendar=fail
        )),
    )
    with pytest.raises(ProviderUnavailableError, match="upstream timeout"):
        asyncio.run(YahooFinanceProvider().calendar())


def test_yahoo_calendar_clamps_requested_limit(monkeypatch):
    called = {}

    def fetch(**kwargs):
        called.update(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(
        yahoo_provider,
        "_yfinance",
        lambda: SimpleNamespace(Calendars=lambda: SimpleNamespace(
            get_economic_events_calendar=fetch
        )),
    )
    asyncio.run(YahooFinanceProvider().calendar(limit=1000))
    assert called["limit"] == 100


@pytest.mark.asyncio
async def test_yahoo_calendar_persistence_preserves_calendar_provenance(monkeypatch):
    monkeypatch.setattr(
        yahoo_provider,
        "_yfinance",
        lambda: SimpleNamespace(Calendars=lambda: SimpleNamespace(
            get_economic_events_calendar=lambda **kwargs: _calendar_frame().iloc[[0]]
        )),
    )
    provider = YahooFinanceProvider()
    monkeypatch.setattr(calendar_service, "get_provider", lambda name: provider)
    monkeypatch.setattr(calendar_service, "insert_economic_event", lambda event: None)
    monkeypatch.setattr(calendar_service, "store_event_snapshot", lambda *args: None)
    monkeypatch.setattr(calendar_service, "insert_event_tags", lambda *args: None)

    events = await calendar_service.fetch_and_store_economic_events("Yahoo Finance", limit=5)
    provenance = await calendar_service.get_calendar_provenance("Yahoo Finance")

    assert events[0].provider_version == "yf-calendar-v1"
    assert events[0].coverage == "Global economic events (best effort)"
    assert events[0].entitlement == "public"
    assert provenance["provider_version"] == "yf-calendar-v1"
    assert provenance["coverage"] == "Global economic events (best effort)"
    assert provenance["entitlement"] == "public"


def test_yahoo_calendar_maps_common_region_codes_to_currency():
    assert yahoo_provider._region_country_currency("MY") == ("MY", "MYR")
    assert yahoo_provider._region_country_currency("KW") == ("KW", "KWD")
    assert yahoo_provider._region_country_currency("unknown") == ("unknown", "")
