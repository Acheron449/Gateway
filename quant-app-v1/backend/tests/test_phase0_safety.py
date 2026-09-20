from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.api import main
from app.config import Settings
from app.services.broker_service import BrokerService, Order, OrderSide, OrderValidationError


def test_live_execution_is_rejected() -> None:
    with pytest.raises(OrderValidationError, match="Live execution"):
        BrokerService(paper_trading=False)


@pytest.mark.parametrize(
    "order",
    [
        Order("SAMPLE_STOCK", OrderSide.BUY, 1, 100),
        Order("AAPL", OrderSide.BUY, 0, 100),
        Order("AAPL", OrderSide.BUY, 1, 0),
    ],
)
def test_placeholder_or_incomplete_orders_are_rejected(order: Order) -> None:
    broker = BrokerService()
    with pytest.raises(OrderValidationError):
        asyncio.run(broker.place_order(order))


def test_non_paper_configuration_is_rejected() -> None:
    with pytest.raises(ValueError, match="paper"):
        Settings(execution_mode="live")


@pytest.mark.asyncio
async def test_history_attaches_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_alpaca_credentials", lambda: ("key", "secret"))
    monkeypatch.setattr(
        main.asyncio,
        "to_thread",
        AsyncMock(return_value=[{"time": 1_700_000_000, "open": 1, "high": 2, "low": 1, "close": 2}]),
    )
    rows = await main.get_history("AAPL", tf="1h")
    assert rows[0]["source"] == "alpaca"
    assert rows[0]["data_time"].endswith("+00:00")
    assert rows[0]["fetched_at"]


@pytest.mark.asyncio
async def test_scraped_news_endpoint_is_explicitly_unavailable() -> None:
    # The old forex-factory endpoint has been replaced with proper news/calendar endpoints
    # that return empty list with unavailable provenance when not configured
    from app.api.v1.news import get_news
    response = await get_news(provider="Finnhub", symbol=None, limit=10)
    assert response.count == 0
    assert response.provenance.get("entitlement") == "unavailable"
