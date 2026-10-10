"""Tests for the economic-calendar API providers and the merged calendar feed."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import EconomicEvent, EventImportance
from app.providers.economic_calendar_provider import (
    EconomicCalendarApiProvider,
    FmpCalendarProvider,
    _impact_int,
    _impact_text,
)
from app.providers import registry
from app.api.v1 import news


def _event(title: str, hour: int, currency: str = "USD") -> EconomicEvent:
    return EconomicEvent(
        id=f"t-{title}-{hour}",
        title=title,
        country="US",
        currency=currency,
        importance=EventImportance.HIGH,
        scheduled_at=datetime(2026, 1, 5, hour, 30, tzinfo=timezone.utc),
        actual=None,
        forecast=None,
        prior=None,
        related_symbols=[],
        provider_version="test-v1",
        source="Test",
    )


def test_providers_registered():
    providers = registry.list_providers()
    assert "EconomicCalendar" in providers
    assert "FinancialModelingPrep" in providers
    assert providers["EconomicCalendar"]["name"] == "EconomicCalendar"
    assert providers["FinancialModelingPrep"]["requires_api_key"] is True


def test_provider_factory_accepts_api_key_arg():
    # The generic registry factory passes api_key=... to every class.
    ec = registry.get_provider("EconomicCalendar")
    fmp = registry.get_provider("FinancialModelingPrep")
    assert isinstance(ec, EconomicCalendarApiProvider)
    assert isinstance(fmp, FmpCalendarProvider)


def test_impact_mappings():
    assert _impact_int(3) == EventImportance.HIGH
    assert _impact_int(2) == EventImportance.MEDIUM
    assert _impact_int(1) == EventImportance.LOW
    assert _impact_text("High") == EventImportance.HIGH
    assert _impact_text("Medium") == EventImportance.MEDIUM
    assert _impact_text("Low") == EventImportance.LOW


def test_economic_calendar_provider_not_configured_without_url(monkeypatch):
    monkeypatch.delenv("ECONOMIC_CALENDAR_API_URL", raising=False)
    assert EconomicCalendarApiProvider().is_configured is False
    monkeypatch.setenv("ECONOMIC_CALENDAR_API_URL", "http://localhost/economic-calendar-api")
    assert EconomicCalendarApiProvider().is_configured is True


def test_fmp_provider_configured_via_env(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("FINANCIALMODELINGPREP_API_KEY", raising=False)
    assert FmpCalendarProvider().is_configured is False
    monkeypatch.setenv("FMP_API_KEY", "fmp-key")
    assert FmpCalendarProvider().is_configured is True


class _StubProvider:
    def __init__(self, name: str, events: list[EconomicEvent], configured: bool = True):
        self._name = name
        self._events = events
        self.is_configured = configured
        self.meta = {"name": name, "version": "v1"}

    @property
    def name(self) -> str:
        return self._name


@pytest.mark.asyncio
async def test_calendar_auto_merges_base_and_additions(monkeypatch):
    # Base feed supplies CPI; a second source supplies CPI (duplicate) + NFP.
    base = [_event("Core CPI m/m", 13)]
    extra = [_event("Core CPI m/m", 13), _event("Non-Farm Payrolls", 13)]

    providers = {
        "EconomicCalendar": _StubProvider("EconomicCalendar", base),
        "FinancialModelingPrep": _StubProvider("FinancialModelingPrep", extra),
    }

    monkeypatch.setattr(news, "get_provider", lambda name: providers.get(name))
    monkeypatch.setattr(
        news,
        "fetch_and_store_economic_events",
        lambda provider_name, limit=20: _async_return(providers[provider_name]._events),
    )

    response = await news.get_calendar(limit=20, provider="auto")
    titles = [e["title"] for e in response.events]
    assert titles.count("Core CPI m/m") == 1  # duplicate collapsed
    assert "Non-Farm Payrolls" in titles  # added on top of the base
    assert response.count == len(response.events)


@pytest.mark.asyncio
async def test_calendar_explicit_provider_is_strict(monkeypatch):
    only = [_event("GDP", 13)]
    providers = {"JBlanked": _StubProvider("JBlanked", only)}

    def _get(name):
        return providers.get(name)

    monkeypatch.setattr(news, "get_provider", _get)
    monkeypatch.setattr(
        news,
        "fetch_and_store_economic_events",
        lambda provider_name, limit=20: _async_return(providers[provider_name]._events),
    )

    response = await news.get_calendar(limit=20, provider="JBlanked")
    assert [e["title"] for e in response.events] == ["GDP"]


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner()
