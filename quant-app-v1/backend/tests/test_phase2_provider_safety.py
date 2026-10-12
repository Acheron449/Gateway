"""Phase 2 provider safety regression tests."""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
import httpx

# Ensure JWT secret is set before any auth imports
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from app.providers.finnhub_provider import FinnhubProvider
from app.providers.base import ProviderUnavailableError
from app.services.llm_providers import normalize_model_catalogue
from app.api.main import app
from app.auth import create_access_token


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def test_model_catalogue_marks_only_explicit_free_metadata():
    models = normalize_model_catalogue(
        "custom-openai",
        [
            {"id": "paid"},
            {"id": "tagged-free", "is_free": True},
            {"id": "string-truthy", "free": "true"},
            {"id": "duplicate", "is_free": False},
            {"id": "duplicate", "is_free": True},
            {"id": ""},
            {"name": "missing-id", "free": True},
            None,
        ],
    )
    assert models == [
        {"id": "duplicate", "is_free": False},
        {"id": "paid", "is_free": False},
        {"id": "string-truthy", "is_free": False},
        {"id": "tagged-free", "is_free": True},
    ]


def test_openrouter_free_variant_requires_free_id_and_zero_text_pricing():
    models = normalize_model_catalogue(
        "openrouter",
        [
            {"id": "paid-model", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "free-model:free", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "unknown-model:free", "pricing": {"prompt": "0", "completion": None}},
            {"id": "invalid-price:free", "pricing": {"prompt": "free", "completion": "0"}},
            {"id": "duplicate:free", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "duplicate:free", "pricing": {"prompt": "0", "completion": None}},
        ],
    )
    assert models == [
        {"id": "duplicate:free", "is_free": False},
        {"id": "free-model:free", "is_free": True},
        {"id": "invalid-price:free", "is_free": False},
        {"id": "paid-model", "is_free": False},
        {"id": "unknown-model:free", "is_free": False},
    ]


@pytest.mark.asyncio
async def test_llm_model_route_requires_auth_and_returns_free_markers(monkeypatch):
    async def fake_catalogue(provider_id, *, use_cache=True):
        assert provider_id == "openrouter"
        assert use_cache is False
        return [{"id": "vendor/free:free", "is_free": True}, {"id": "vendor/paid", "is_free": False}]

    monkeypatch.setattr("app.api.v1.llm.svc.fetch_model_catalogue", fake_catalogue)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        anonymous = await client.get("/llm/providers/openrouter/models")
        assert anonymous.status_code == 401

        token = create_access_token({"sub": "model-catalogue-test", "email": "model-catalogue@local.test"})
        response = await client.get(
            "/llm/providers/openrouter/models",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "provider": "openrouter",
        "models": [
            {"id": "vendor/free:free", "is_free": True},
            {"id": "vendor/paid", "is_free": False},
        ],
    }


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
