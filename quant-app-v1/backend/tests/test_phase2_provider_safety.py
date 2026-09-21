"""Phase 2 provider safety regression tests."""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure JWT secret is set before any auth imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from app.providers.finnhub_provider import FinnhubProvider
from app.providers.base import ProviderUnavailableError


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def test_finnhub_header_no_token_in_url(monkeypatch):
    resp = FakeResponse(200, {"c": 150.25, "t": 1_700_000_000, "d": 0.0, "dp": 0.0})
    client = MagicMock()
    # async get called with params headers
    async def mock_get(url, params=None, headers=None):
        mock_get.call_args = (url, params, headers)
        return resp
    monkeypatch.setattr(FinnhubProvider, "_http", property(lambda self: MagicMock(get=mock_get)))
    provider = FinnhubProvider(api_key="sk-test")
    res = asyncio.run(provider.quote("AAPL"))
    assert res is not None
    args, params, headers = mock_get.call_args
    assert "X-Finnhub-Token" in headers
    assert "token" not in (params or {}).get("symbol", "")


def test_invalid_quote_raises_unavailable(monkeypatch):
    resp_bad = FakeResponse(500, None)
    client = MagicMock()
    async def mock_get(url, params=None, headers=None):
        return resp_bad
    monkeypatch.setattr(FinnhubProvider, "_http", property(lambda self: MagicMock(get=mock_get)))
    provider = FinnhubProvider(api_key="sk-test")
    with pytest.raises(ProviderUnavailableError):
        asyncio.run(provider.quote("AAPL"))


def test_empty_configured_results(monkeypatch):
    class FakeProvider:
        name = "Finnhub"
        @property
        def meta(self):
            return {"name":"Finnhub","version":"finnhub-v1","endpoint":"https://finnhub.io/api/v1","requires_api_key":True,"rate_limit_per_min":60}
        @property
        def is_configured(self):
            return True
        async def news(self, symbol=None, limit=5):
            return []
        async def calendar(self, limit=5):
            return []
    monkeypatch.setattr("app.providers.registry.get_provider", lambda x: FakeProvider())
    from app.api.v1.news import get_news, get_calendar
    news_resp = asyncio.run(get_news(provider="Finnhub", symbol=None, limit=10))
    assert news_resp.items == []
    cal_resp = asyncio.run(get_calendar(provider="Finnhub", limit=20))
    assert cal_resp.events == []
