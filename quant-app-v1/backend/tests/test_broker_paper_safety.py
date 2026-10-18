from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.services import alpaca_live
from app.services.broker_service import Order, OrderSide
from app.services.alpaca_live import AlpacaLiveProvider
from app.api.main import app
from app.services import ai_trading


def _get_live_provider_factory():
    from app.api.v1.live import get_provider

    return get_provider


@pytest.mark.parametrize(
    "url",
    [
        "https://api.alpaca.markets",
        "https://paper-api.alpaca.markets.evil.com",
        "http://paper-api.alpaca.markets",
        "https://user:pass@paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets:444",
    ],
)
def test_provider_rejects_non_paper_execution_origin(url: str) -> None:
    with pytest.raises(ValueError):
        AlpacaLiveProvider("key", "secret", url, paper=True)


def test_provider_rejects_non_paper_mode() -> None:
    with pytest.raises(ValueError, match="paper"):
        AlpacaLiveProvider("key", "secret", paper=False)


@pytest.mark.asyncio
async def test_place_order_is_disabled_until_durable_intent_recovery_exists() -> None:
    provider = AlpacaLiveProvider("key", "secret")
    with pytest.raises(RuntimeError, match="durable"):
        await provider.place_order(Order("AAPL", OrderSide.BUY, 1, 100))


@pytest.mark.asyncio
async def test_request_revalidates_origin_before_creating_session(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AlpacaLiveProvider("key", "secret")
    provider.base_url = "https://paper-api.alpaca.markets.evil.com"
    session_factory = Mock(side_effect=AssertionError("network session must not be created"))
    monkeypatch.setattr(alpaca_live.aiohttp, "ClientSession", session_factory)

    with pytest.raises(ValueError):
        await provider._request("GET", "/v2/account")

    session_factory.assert_not_called()


class _Response:
    status = 302
    headers: dict[str, str] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def text(self) -> str:
        return "redirect"


class _Session:
    closed = False

    def __init__(self):
        self.observed = {}

    def request(self, method: str, url: str, **kwargs):
        self.observed.update(method=method, url=url, **kwargs)
        return _Response()


@pytest.mark.asyncio
async def test_request_refuses_redirect_and_does_not_follow(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    provider = AlpacaLiveProvider("key", "secret")
    provider._session = session
    monkeypatch.setattr(alpaca_live.aiohttp, "ClientSession", lambda *args, **kwargs: session)

    with pytest.raises(RuntimeError, match="redirect"):
        await provider._request("GET", "/v2/account")

    assert session.observed["allow_redirects"] is False
    assert session.observed["url"] == "https://paper-api.alpaca.markets/v2/account"


def test_broker_account_routes_are_not_mounted() -> None:
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert not any(path.startswith("/live/") or path == "/live" for path in paths)


def test_direct_provider_factory_is_fail_closed() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        _get_live_provider_factory()()
    assert error.value.status_code == 503
    assert "unavailable" in str(error.value.detail).lower()


@pytest.mark.asyncio
async def test_ai_live_order_helper_is_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="unavailable"):
        await ai_trading.place_live_order_async("AAPL", "buy", 1)


def test_ai_trading_config_cannot_restore_live_route(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    path = tmp_path / "ai_trading.json"
    path.write_text('{"enabled": false, "route": "live"}', encoding="utf-8")
    monkeypatch.setattr(ai_trading, "_CONFIG_FILE", path)

    assert ai_trading.get_config()["route"] == "paper"
    saved = ai_trading.save_config({**ai_trading.get_config(), "route": "live"})
    assert saved["route"] == "paper"
    assert ai_trading.get_config()["route"] == "paper"


def test_broker_modules_contain_no_live_trading_origin_literal() -> None:
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    for relative in ("app/services/alpaca_live.py", "app/services/broker_service.py"):
        source = (backend / relative).read_text(encoding="utf-8")
        assert "https://api.alpaca.markets" not in source
