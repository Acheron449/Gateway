from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest

from app.services import broker_service
from app.services.broker_service import OrderValidationError, _AlpacaProvider


@pytest.mark.parametrize(
    "url",
    [
        "https://paper-api.alpaca.markets.evil.com",
        "https://evil.com/paper-api.alpaca.markets",
        "http://paper-api.alpaca.markets",
        "https://user:pass@paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets:444",
        "https://paper-api.alpaca.markets/v2",
        "https://paper-api.alpaca.markets/?redirect=https://evil.example",
    ],
)
def test_alpaca_provider_rejects_noncanonical_paper_origins(url: str) -> None:
    with pytest.raises(OrderValidationError):
        _AlpacaProvider("key", "secret", url, paper=True)


def test_alpaca_provider_rejects_non_paper_mode() -> None:
    with pytest.raises(OrderValidationError, match="paper"):
        _AlpacaProvider("key", "secret", "https://paper-api.alpaca.markets", paper=False)


@pytest.mark.asyncio
async def test_order_submission_is_disabled_until_durable_lifecycle_exists() -> None:
    provider = _AlpacaProvider("key", "secret", "https://paper-api.alpaca.markets", paper=True)
    from app.services.broker_service import Order, OrderSide

    with pytest.raises(OrderValidationError, match="durable"):
        await provider.place_order(Order("AAPL", OrderSide.BUY, 1, 100))


@pytest.mark.asyncio
async def test_request_revalidates_final_url_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _AlpacaProvider("key", "secret", "https://paper-api.alpaca.markets", paper=True)
    provider.base_url = "https://paper-api.alpaca.markets.evil.com"
    session_factory = Mock(side_effect=AssertionError("network session must not be created"))
    monkeypatch.setattr(broker_service.aiohttp, "ClientSession", session_factory)

    with pytest.raises(OrderValidationError):
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
        return "redirect response"


class _Session:
    def __init__(self, observed: dict):
        self.observed = observed

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def request(self, method: str, url: str, **kwargs):
        self.observed.update(method=method, url=url, **kwargs)
        return _Response()


@pytest.mark.asyncio
async def test_request_refuses_redirect_without_following(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict = {}
    monkeypatch.setattr(broker_service.aiohttp, "ClientSession", lambda: _Session(observed))
    provider = _AlpacaProvider("key", "secret", "https://paper-api.alpaca.markets", paper=True)

    with pytest.raises(RuntimeError, match="redirect"):
        await provider._request("GET", "/v2/account")

    assert observed["allow_redirects"] is False
    assert observed["url"] == "https://paper-api.alpaca.markets/v2/account"
