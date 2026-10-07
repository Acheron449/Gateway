"""Regression tests for the HTTP 500s observed on the Vercel deployment.

There the function filesystem is read-only and .vercelignore excludes
``app/settings/`` and ``data/``. Three unhandled failures behind that used to
take down provider-backed routes with a bare 500:

* ``registry._ensure_settings_dir()`` raised ``OSError: [Errno 30] Read-only
  file system`` — every ``get_provider()`` call (news chain, calendar chain,
  ``/quote`` default provider, ``/news/providers``).
* ``InstrumentCatalogueError`` from ``/stocks/{ticker}/metadata`` (catalogue
  excluded from the bundle).
* ``QuoteResponse(**quote)`` pydantic ``ValidationError`` for providers that
  return ``symbol``/``price`` instead of ``instrument``/``provenance``.

Second round (LLM providers):

* ``llm_providers._ensure_dir()`` hit the same EROFS on the bundled
  ``app/settings`` dir — ``GET /llm/providers`` 500'd ("internal server error
  for llm provider retrieval").
* ``GATEWAY_PROVIDER_KEY`` missing on Vercel — saving a provider API key
  raised ``RuntimeError`` (``/settings/providers/{name}/key`` → 503,
  ``PUT /llm/providers/{id}`` → 400).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.api.main import app
from app.api.v1 import stocks as stocks_api
from app.providers import registry
from app.services import llm_providers as llm_svc
from app.services.catalogue import InstrumentCatalogueError


async def fetch(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


class _ReadOnlyDir:
    """Stands in for the read-only Vercel bundle path (errno 30, EROFS).

    Raises the exact error captured in the production traceback:
    ``OSError: [Errno 30] Read-only file system: '/var/task/app/settings'``.
    """

    def mkdir(self, *args, **kwargs) -> None:
        raise OSError(30, "Read-only file system: '/var/task/app/settings'")


def _install_readonly_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_SETTINGS_DIR", _ReadOnlyDir())
    monkeypatch.setattr(
        registry, "_SETTINGS_FILE", Path("/var/task/app/settings/provider_keys.json")
    )
    monkeypatch.setenv("GATEWAY_DATA_DIR", str(tmp_path))


class TestReadOnlyBundleSettings:
    def test_load_settings_relocates_when_bundle_is_read_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_readonly_bundle(tmp_path, monkeypatch)

        # Must not raise: reads degrade to "no stored keys".
        assert registry._load_settings() == {}
        assert registry._SETTINGS_DIR == tmp_path / "provider_settings"
        assert registry._SETTINGS_DIR.is_dir()

    def test_provider_key_roundtrip_after_relocation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_readonly_bundle(tmp_path, monkeypatch)
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        # The exact production crash site: get_provider() -> _read_api_key()
        # -> _load_settings() used to raise EROFS.
        registry._store_api_key("Finnhub", "fh-secret")
        assert registry.has_stored_key("Finnhub")
        assert registry._read_api_key("Finnhub") == "fh-secret"

        provider = registry.get_provider("Finnhub")
        assert provider is not None and provider.is_configured is True

        assert registry._delete_api_key("Finnhub") is True
        assert registry._read_api_key("Finnhub") is None

    @pytest.mark.asyncio
    async def test_news_providers_endpoint_survives_read_only_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_readonly_bundle(tmp_path, monkeypatch)
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        response = await fetch("/news/providers")
        assert response.status_code == 200
        body = response.json()
        assert "Finnhub" in body["providers"]
        assert body["providers"]["Finnhub"]["configured"] is False

    @pytest.mark.asyncio
    async def test_quote_unconfigured_provider_returns_503_not_500(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(registry, "_SETTINGS_DIR", tmp_path / "settings")
        monkeypatch.setattr(
            registry, "_SETTINGS_FILE", tmp_path / "settings" / "provider_keys.json"
        )
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        response = await fetch("/quote/AAPL")  # default provider: Finnhub
        assert response.status_code == 503
        assert response.json()["status"] == "unavailable"

    def test_bundled_dir_stays_in_place_when_writable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Local/Docker runs must keep using app/settings/ (no silent move).
        bundled = tmp_path / "settings"
        monkeypatch.setattr(registry, "_SETTINGS_DIR", bundled)
        monkeypatch.setattr(registry, "_SETTINGS_FILE", bundled / "provider_keys.json")

        registry._ensure_settings_dir()
        assert registry._SETTINGS_DIR == bundled
        assert bundled.is_dir()


def _install_readonly_llm_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_svc, "_SETTINGS_DIR", _ReadOnlyDir())
    monkeypatch.setattr(
        llm_svc, "_SETTINGS_FILE", Path("/var/task/app/settings/llm_providers.json")
    )
    monkeypatch.setenv("GATEWAY_DATA_DIR", str(tmp_path))


class TestReadOnlyLlmProviderSettings:
    def test_llm_settings_relocate_when_bundle_is_read_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_readonly_llm_bundle(tmp_path, monkeypatch)

        # Must not raise: reads degrade to "no saved providers".
        assert llm_svc._load_store() == {}
        assert llm_svc._SETTINGS_DIR == tmp_path / "provider_settings"
        assert llm_svc._SETTINGS_DIR.is_dir()

    @pytest.mark.asyncio
    async def test_llm_providers_endpoint_survives_read_only_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_readonly_llm_bundle(tmp_path, monkeypatch)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        # The exact production crash site: GET /llm/providers -> _load_store()
        # -> _ensure_dir() used to raise EROFS ("internal server error").
        response = await fetch("/llm/providers")
        assert response.status_code == 200
        body = response.json()
        assert body["providers"], "catalogue must not be empty"
        by_id = {p["id"]: p for p in body["providers"]}
        # Keyed provider with no env key and no stored key reports unconfigured.
        assert by_id["openrouter"]["has_key"] is False
        assert by_id["openrouter"]["configured"] is False
        # Keyless entries stay available so local Ollama still works.
        assert by_id["ollama-local"]["key_required"] is False

    def test_llm_key_roundtrip_after_relocation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_readonly_llm_bundle(tmp_path, monkeypatch)
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        llm_svc.save_provider_settings("openrouter", api_key="sk-or-test")
        assert llm_svc.stored_api_key("openrouter") == "sk-or-test"
        assert llm_svc.has_usable_key(llm_svc.CATALOG_BY_ID["openrouter"]) is True

        assert llm_svc.delete_provider_key("openrouter") is True
        assert llm_svc.stored_api_key("openrouter") is None

    def test_llm_key_save_without_encryption_key_raises_clear_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exact production failure: no GATEWAY_PROVIDER_KEY on Vercel.
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", "")
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY_FILE", "")

        with pytest.raises(llm_svc.LlmError) as excinfo:
            llm_svc.save_provider_settings("openrouter", api_key="sk-or-test")
        assert "GATEWAY_PROVIDER_KEY" in str(excinfo.value)


class TestCatalogueDegradation:
    @pytest.mark.asyncio
    async def test_metadata_returns_503_when_catalogue_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(ticker: str):
            raise InstrumentCatalogueError(
                "Instrument catalogue not found at /var/task/data/instruments/catalogue_v1.json"
            )

        monkeypatch.setattr(stocks_api, "get_instrument", _raise)
        response = await fetch("/stocks/AAPL/metadata")
        assert response.status_code == 503


class _YahooShapeQuoteProvider:
    """Quote payload shaped like Yahoo's (symbol/price, no provenance)."""

    name = "Yahoo Finance"
    meta = {"version": "yf-v1"}
    is_configured = True

    def __init__(self, api_key: str = "") -> None:
        self.api_key = api_key

    async def quote(self, symbol: str):
        return {
            "symbol": symbol.upper(),
            "price": 123.45,
            "change": 1.5,
            "change_pct": 1.23,
            "provider_version": "yf-v1",
        }


class TestQuotePayloadNormalization:
    @pytest.mark.asyncio
    async def test_symbol_price_payload_maps_to_quote_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(
            registry._PROVIDER_CLASSES, "QuoteShapeTest", _YahooShapeQuoteProvider
        )

        response = await fetch("/quote/AAPL?provider=QuoteShapeTest")
        assert response.status_code == 200
        body = response.json()
        assert body["instrument"] == "AAPL"
        assert body["last_price"] == 123.45
        assert body["status"] == "available"
        assert body["provenance"]["source"] == "Yahoo Finance"
        assert body["provenance"]["provider_version"] == "yf-v1"
