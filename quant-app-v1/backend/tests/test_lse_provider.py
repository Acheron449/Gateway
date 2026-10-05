"""Tests for London Strategic Edge (LSE) vault compatibility.

Everything here is hermetic: HTTP is stubbed at ``httpx.MockTransport`` so
the suite never depends on api.londonstrategicedge.com being reachable.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.api import main as main_api
from app.providers import registry
from app.providers.base import ProviderUnavailableError
from app.providers.lse_provider import LSEProvider


def _transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _epoch(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


class TestRegistry:
    def test_provider_listed_with_vault_metadata(self) -> None:
        providers = registry.list_providers()
        assert "London Strategic Edge" in providers
        meta = providers["London Strategic Edge"]
        assert meta["requires_api_key"] is True
        assert meta["endpoint"] == "https://api.londonstrategicedge.com/vault"

    def test_unconfigured_provider_reports_missing_key(self) -> None:
        provider = registry.get_provider("London Strategic Edge")
        # No key stored and no LSE_API_KEY in the test environment.
        assert provider is not None
        assert provider.is_configured is False

    def test_browser_managed_key_roundtrip(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(registry, "_SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(registry, "_SETTINGS_FILE", tmp_path / "provider_keys.json")
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())
        monkeypatch.delenv("LSE_API_KEY", raising=False)

        registry._store_api_key("London Strategic Edge", "lse-test-key")
        assert registry.has_stored_key("London Strategic Edge")
        assert registry._read_api_key("London Strategic Edge") == "lse-test-key"

        provider = registry.get_provider("London Strategic Edge")
        assert provider is not None and provider.is_configured is True

        assert registry._delete_api_key("London Strategic Edge") is True
        assert registry._read_api_key("London Strategic Edge") is None

    def test_env_var_key_fallback(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(registry, "_SETTINGS_DIR", tmp_path)
        monkeypatch.setattr(registry, "_SETTINGS_FILE", tmp_path / "provider_keys.json")
        monkeypatch.setenv("LSE_API_KEY", "env-lse-key")
        assert registry._read_api_key("London Strategic Edge") == "env-lse-key"


class TestLSEProvider:
    def test_provider_without_key_short_circuits(self) -> None:
        provider = LSEProvider("")
        assert provider.is_configured is False
        assert asyncio.run(provider.history("AAPL", "1d", "1y")) is None
        assert asyncio.run(provider.quote("AAPL")) is None

    def test_history_maps_interval_range_and_normalizes_rows(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            seen["key"] = request.headers.get("x-api-key")
            return httpx.Response(
                200,
                json=[
                    {
                        "ts": "2026-01-02 09:30:00",
                        "open": 100,
                        "high": 105,
                        "low": 99,
                        "close": 103,
                        "volume": 1234,
                    },
                    # FX-style bar without volume must default to 0.
                    {
                        "ts": "2026-01-02 09:31:00",
                        "open": 103,
                        "high": 104,
                        "low": 102,
                        "close": 102.5,
                    },
                ],
            )

        provider = LSEProvider("key-123", client=_transport(handler))
        rows = asyncio.run(provider.history("aapl", "1h", "1mo"))

        assert seen["path"] == "/vault/candles"
        assert seen["key"] == "key-123"
        assert seen["params"]["symbol"] == "AAPL"
        assert seen["params"]["timeframe"] == "1h"
        assert seen["params"]["order"] == "asc"
        assert seen["params"]["start"]  # lookback derived from the range

        assert rows is not None and len(rows) == 2
        assert rows[0]["time"] == _epoch("2026-01-02 09:30:00")
        assert rows[0]["close"] == 103.0
        assert rows[0]["volume"] == 1234.0
        assert rows[1]["volume"] == 0.0
        assert rows[1]["timestamp"].endswith("+00:00")
        assert rows[0]["symbol"] == "AAPL"

    def test_gateway_weekly_interval_maps_to_vault_timeframe(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=[])

        provider = LSEProvider("k", client=_transport(handler))
        rows = asyncio.run(provider.history("BTC/USD", "1wk", "5y"))
        assert rows == []
        assert seen["params"]["timeframe"] == "1w"
        assert seen["params"]["symbol"] == "BTC/USD"

    def test_http_error_surfaces_status_and_detail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"detail": "quota exceeded"})

        provider = LSEProvider("k", client=_transport(handler))
        with pytest.raises(ProviderUnavailableError) as excinfo:
            asyncio.run(provider.history("AAPL", "1d", "1y"))
        assert excinfo.value.status_code == 403
        assert "quota exceeded" in str(excinfo.value)

    def test_transport_failure_is_provider_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        provider = LSEProvider("k", client=_transport(handler))
        with pytest.raises(ProviderUnavailableError):
            asyncio.run(provider.history("AAPL", "1d", "1y"))

    def test_quote_uses_latest_two_candles(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(
                200,
                json=[
                    {"ts": "2026-01-02 16:00:00", "close": 150.5, "open": 149.5,
                     "high": 151.0, "low": 149.0, "volume": 100},
                    {"ts": "2026-01-02 15:59:00", "close": 149.0, "open": 148.5,
                     "high": 149.5, "low": 148.0, "volume": 90},
                ],
            )

        provider = LSEProvider("k", client=_transport(handler))
        quote = asyncio.run(provider.quote("aapl"))

        assert seen["params"]["timeframe"] == "1m"
        assert seen["params"]["order"] == "desc"
        assert seen["params"]["limit"] == "2"

        assert quote is not None
        assert quote["instrument"] == "AAPL"
        assert quote["last_price"] == 150.5
        assert quote["change"] == pytest.approx(1.5)
        assert quote["change_pct"] == pytest.approx(1.5 / 149.0 * 100.0)
        assert quote["provenance"]["source"] == "London Strategic Edge"
        assert quote["provenance"]["data_time"] is not None


class TestHistoryEndpointIntegration:
    def test_alias_ids_resolve_to_canonical_name(self) -> None:
        for alias in (
            "lse",
            "London Strategic Edge",
            "london strategic edge",
            "londonstrategicedge",
            "london-strategic-edge",
        ):
            assert main_api._canonical_history_provider(alias) == "London Strategic Edge"

    def test_provider_catalogue_offers_lse_entry(self) -> None:
        entry = next(
            (item for item in main_api._history_provider_catalogue() if item["id"] == "lse"),
            None,
        )
        assert entry is not None
        assert entry["name"] == "London Strategic Edge"
        assert entry["is_default"] is False

    @pytest.mark.asyncio
    async def test_alt_provider_branch_fetches_from_lse(self, monkeypatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {"ts": "2026-01-02 10:00:00", "open": 10, "high": 11,
                     "low": 9.5, "close": 10.5, "volume": 500},
                ],
            )

        def fake_registry(name: str):
            if name == "London Strategic Edge":
                return LSEProvider("k", client=_transport(handler))
            return None

        monkeypatch.setattr(main_api, "get_registry_provider", fake_registry)
        rows = await main_api._fetch_history_alt_provider_sync(
            "London Strategic Edge", "aapl", "1d"
        )
        assert rows is not None and len(rows) == 1
        candle = rows[0]
        assert candle["close"] == 10.5
        assert candle["volume"] == 500.0
        assert candle["time"] == _epoch("2026-01-02 10:00:00")
