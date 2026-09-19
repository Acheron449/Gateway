from __future__ import annotations

import httpx
import pandas as pd
import pytest

from app.api.main import app
from app.config import Settings
from app.models import Instrument, Order, OrderSide, Portfolio, Quote, provenance_now
from app.services import market_data
from app.services.catalogue import (
    InstrumentCatalogueError,
    get_instrument,
    list_instruments,
    load_catalogue,
    search_instruments,
)


async def fetch(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


# --- Domain model records ---

def test_instrument_requires_provenance() -> None:
    with pytest.raises(Exception):
        Instrument(symbol="AAPL", name="Apple Inc", exchange="NASDAQ")


def test_instrument_normalizes_and_validates_symbol() -> None:
    provenance = provenance_now(source="gateway-instrument-catalogue", provider_version="catalogue-v1")
    instrument = Instrument(symbol="aapl", name="Apple Inc", exchange="NASDAQ", provenance=provenance)
    assert instrument.symbol == "AAPL"
    with pytest.raises(Exception):
        Instrument(symbol="BAD SYMBOL!", name="x", exchange="NASDAQ", provenance=provenance)
    with pytest.raises(Exception):
        Instrument(symbol="THISISWAYTOOLONGX", name="x", exchange="NASDAQ", provenance=provenance)


def test_quote_and_portfolio_carry_provenance_and_are_typed() -> None:
    provenance = provenance_now(source="alpaca", provider_version="alpaca-quotes-v1", coverage="US equities / real-time")
    quote = Quote(instrument="AAPL", last_price=200.0, bid=199.9, ask=200.1, provenance=provenance)
    assert quote.provenance.source == "alpaca"
    assert quote.last_price == 200.0
    portfolio = Portfolio(id="p1", cash=100_000.0)
    assert portfolio.account_id == "paper"
    assert portfolio.positions == []


def test_domain_order_rejects_live_and_placeholders() -> None:
    with pytest.raises(Exception, match="paper"):
        Order(id="o1", instrument="AAPL", side=OrderSide.BUY, quantity=1, execution_mode="live")
    with pytest.raises(Exception):
        Order(id="o2", instrument="SAMPLE_STOCK", side=OrderSide.BUY, quantity=1)
    with pytest.raises(Exception):
        Order(id="o3", instrument="AAPL", side=OrderSide.BUY, quantity=0)
    with pytest.raises(Exception):
        Order(id="o4", instrument="", side=OrderSide.BUY, quantity=1)


# --- Versioned instrument catalogue ---

def test_catalogue_contains_original_universe_and_more() -> None:
    symbols = {instrument.symbol for instrument in list_instruments()}
    assert {"AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"} <= symbols
    assert len(symbols) > 10


def test_catalogue_is_versioned_with_provenance() -> None:
    catalogue = load_catalogue()
    assert catalogue["metadata"]["catalogue_version"]
    assert catalogue["metadata"]["schema_version"]
    provenance = catalogue["provenance"]
    assert provenance.source == "gateway-instrument-catalogue"
    assert provenance.data_time is not None
    for instrument in list_instruments():
        assert instrument.provenance.source == "gateway-instrument-catalogue"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("AAPL", {"AAPL"}),
        ("aapl", {"AAPL"}),
        ("MS", {"MSFT", "META"}),
        ("lphabet", {"GOOGL"}),
        ("Goldman", {"GS"}),
        ("TICK", set()),
        ("", set()),
    ],
)
def test_catalogue_search(query: str, expected: set[str]) -> None:
    matches = {instrument.symbol for instrument in search_instruments(query)}
    assert matches == expected


def test_get_instrument_unknown_returns_none() -> None:
    assert get_instrument("TICK") is None
    assert get_instrument("EURUSD") is None


def test_missing_catalogue_raises_typed_error(tmp_path) -> None:
    missing = tmp_path / "missing.json"
    load_catalogue.cache_clear()
    with pytest.raises(InstrumentCatalogueError):
        load_catalogue(missing)
    load_catalogue.cache_clear()


# --- HTTP layer ---

@pytest.mark.asyncio
async def test_catalogue_endpoint_reports_version_without_secrets() -> None:
    body = (await fetch("/catalogue")).json()
    assert "catalogue_version" in body
    assert "provenance" in body
    assert "API_KEY" not in str(body).upper()
    assert "secret" not in str(body).lower()


@pytest.mark.asyncio
async def test_catalogue_search_endpoint_returns_typed_records() -> None:
    body = (await fetch("/catalogue/search?query=AAPL")).json()
    assert body["query"] == "AAPL"
    assert "AAPL" in body["matches"]
    instruments = body["instruments"]
    assert instruments
    assert instruments[0]["symbol"] == "AAPL"
    assert "provenance" in instruments[0]
    assert instruments[0]["provenance"]["source"] == "gateway-instrument-catalogue"


@pytest.mark.asyncio
async def test_legacy_stocks_search_is_catalogue_backed() -> None:
    body = (await fetch("/stocks/search?query=ms")).json()
    assert "MSFT" in body["matches"]
    assert "instruments" in body


@pytest.mark.asyncio
async def test_stocks_metadata_includes_catalogue_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_ohlcv(ticker: str, limit: int = 500):
        df = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [1.0], "Close": [2.0], "Volume": [100]}
        )
        return df

    monkeypatch.setattr(market_data, "fetch_ohlcv", _fake_ohlcv)
    body = (await fetch("/stocks/AAPL/metadata")).json()
    assert body["ticker"] == "AAPL"
    assert body["name"] == "Apple Inc"
    assert body["last_close"] == 2.0
    assert body["provenance"]["source"] == "gateway-instrument-catalogue"


@pytest.mark.asyncio
async def test_stocks_metadata_unknown_symbol_404() -> None:
    resp = await fetch("/stocks/TICK/metadata")
    assert resp.status_code == 404
    assert "not in the supported instrument catalogue" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_health_reports_capabilities() -> None:
    body = (await fetch("/health")).json()
    assert body["execution_mode"] == "paper"
    assert body["capabilities"]["live_execution"] is False


def test_env_profiles_are_paper_only() -> None:
    for profile in ("local", "test", "paper", "production"):
        settings = Settings(environment=profile, execution_mode="paper")
        assert settings.capabilities["paper_execution"] is True
        assert settings.capabilities["live_execution"] is False