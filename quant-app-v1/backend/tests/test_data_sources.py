"""Tests for the yfinance news source, ccxt backup provider, and filings feed.

Everything here is hermetic: network calls are stubbed at the module seam so
the suite never depends on Yahoo/Kraken/EDGAR being reachable.
"""

from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.api.v1 import filings as filings_api
from app.api.v1 import news as news_api
from app.providers import yahoo_provider
from app.providers.base import ProviderUnavailableError
from app.providers.ccxt_provider import CCXTProvider, to_exchange_symbol


# ---------------------------------------------------------------------------
# Yahoo Finance (yfinance) news source
# ---------------------------------------------------------------------------

_ARTICLE = {
    "uuid": "abc-123",
    "title": "Test headline for the feed",
    "publisher": "Example Wire",
    "link": "https://example.com/story",
    "providerPublishTime": 1_790_000_000,
    "type": "STORY",
    "thumbnail": {"resolutions": [{"url": "https://example.com/thumb.jpg"}]},
}


def test_yahoo_news_maps_articles_to_news_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """Articles keep their publisher and gain a thumbnail preview."""
    monkeypatch.setattr(yahoo_provider, "_fetch_yahoo_news_sync", lambda q, n: [_ARTICLE])

    provider = yahoo_provider.YahooFinanceProvider()
    items = __import__("asyncio").run(provider.news(symbol="aapl", limit=5))

    assert len(items) == 1
    item = items[0]
    assert item.headline == "Test headline for the feed"
    assert item.source == "Example Wire"  # publisher preserved
    assert item.thumbnail == "https://example.com/thumb.jpg"
    assert item.related_symbols == ["AAPL"]
    assert item.id.startswith("yf-news-")
    assert item.published_at.tzinfo is not None


def test_yahoo_news_failure_surfaces_as_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Upstream failures raise the canonical error so the chain can move on."""

    def _boom(query: str, limit: int):
        raise RuntimeError("network down")

    monkeypatch.setattr(yahoo_provider, "_fetch_yahoo_news_sync", _boom)
    provider = yahoo_provider.YahooFinanceProvider()

    with pytest.raises(ProviderUnavailableError):
        __import__("asyncio").run(provider.news(symbol="AAPL", limit=5))


# ---------------------------------------------------------------------------
# News endpoint source chain (auto = Finnhub -> Yahoo Finance)
# ---------------------------------------------------------------------------


class _StubProvider:
    def __init__(self, name: str, configured: bool) -> None:
        self.name = name
        self.is_configured = configured
        self.meta = {"name": name, "version": f"{name}-v1"}


@pytest.mark.asyncio
async def test_news_auto_chain_falls_back_to_yahoo(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=auto skips an unconfigured Finnhub and uses yfinance."""
    from app.models import NewsItem

    now = datetime.now(timezone.utc)
    story = NewsItem(
        id="yf-news-test",
        headline="Wire story",
        url="https://example.com/a",
        source="Example Wire",
        published_at=now,
        fetched_at=now,
        provider_version="yf-news-v1",
    )

    def _get_provider(name: str):
        if name == "Finnhub":
            return _StubProvider("Finnhub", configured=False)
        if name == "Yahoo Finance":
            return _StubProvider("Yahoo Finance", configured=True)
        return None

    async def _fetch(provider_name: str, symbol=None, limit: int = 20):
        return [story] if provider_name == "Yahoo Finance" else []

    async def _provenance(provider_name: str = "Finnhub"):
        return {"source": provider_name, "provider_version": "stub", "coverage": "news", "entitlement": "x"}

    monkeypatch.setattr(news_api, "get_provider", _get_provider)
    monkeypatch.setattr(news_api, "fetch_and_store_news", _fetch)
    monkeypatch.setattr(news_api, "get_news_provenance", _provenance)

    response = await news_api.get_news(symbol=None, limit=5, provider="auto")
    assert response.count == 1
    assert response.provenance["source"] == "Yahoo Finance"
    assert response.items[0]["source"] == "Example Wire"


@pytest.mark.asyncio
async def test_news_explicit_missing_provider_is_unavailable() -> None:
    """Naming a provider strictly reports when it doesn't exist."""
    response = await news_api.get_news(symbol=None, limit=5, provider="DoesNotExist")
    assert response.status == "unavailable"
    assert response.count == 0
    assert "not available" in (response.message or "")


# ---------------------------------------------------------------------------
# CCXT backup provider
# ---------------------------------------------------------------------------


def test_ccxt_symbol_mapping_forms() -> None:
    """Gateway symbol forms map onto ccxt market ids.

    Non-crypto symbols are allowed through the mapper on purpose — the
    exchange itself rejects them (``does not have market symbol``) and the
    provider wraps that as ProviderUnavailableError so /history falls back
    to yfinance.  Covered by the provider test below.
    """
    assert to_exchange_symbol("BTC-USD") == "BTC/USD"
    assert to_exchange_symbol("BTC-USDT") == "BTC/USDT"
    assert to_exchange_symbol("BTCUSDT") == "BTC/USDT"
    assert to_exchange_symbol("btc/usd") == "BTC/USD"
    assert to_exchange_symbol("ETH") == "ETH/USD"


class _FakeExchange:
    def fetch_ohlcv(self, symbol, timeframe=None, since=None, limit=None):
        # ccxt rows are [ms_timestamp, open, high, low, close, volume]
        return [[1_790_000_000_000, 100.0, 110.0, 90.0, 105.0, 12.5]]

    def fetch_ticker(self, symbol):
        return {"last": 105.0, "open": 100.0, "percentage": 5.0}


def test_ccxt_provider_normalizes_ohlcv_and_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raw ccxt rows normalize to Gateway candles (seconds epoch) and quotes."""
    fake_ccxt = types.SimpleNamespace(kraken=lambda cfg: _FakeExchange())
    monkeypatch.setattr("app.providers.ccxt_provider._ccxt", lambda: fake_ccxt)

    provider = CCXTProvider()
    assert provider.is_configured is True

    import asyncio

    candles = asyncio.run(provider.history("BTC-USD", interval="1d", range="1y"))
    assert candles == [
        {"time": 1_790_000_000, "open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0, "volume": 12.5}
    ]

    quote = asyncio.run(provider.quote("BTC-USD"))
    assert quote is not None
    assert quote["price"] == 105.0
    assert quote["change_pct"] == 5.0


def test_ccxt_wraps_exchange_rejection_for_non_crypto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exchange rejections (e.g. AAPL/USD doesn't exist) surface as the
    canonical provider error, which is what makes /history fall back."""

    class _Rejecting:
        def fetch_ohlcv(self, *args, **kwargs):
            raise ValueError("kraken does not have market symbol AAPL/USD")

    fake_ccxt = types.SimpleNamespace(kraken=lambda cfg: _Rejecting())
    monkeypatch.setattr("app.providers.ccxt_provider._ccxt", lambda: fake_ccxt)

    import asyncio

    with pytest.raises(ProviderUnavailableError):
        asyncio.run(CCXTProvider().history("AAPL", interval="1d", range="1y"))


# ---------------------------------------------------------------------------
# /history ccxt backup (yfinance failure path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_uses_ccxt_backup_when_yfinance_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import main

    def _yf_fails(ticker: str, tf: str):
        raise HTTPException(status_code=502, detail="No history data available")

    rows = [{"time": 1_790_000_000, "open": 1, "high": 2, "low": 1, "close": 2}]
    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", _yf_fails)
    monkeypatch.setattr(main, "_ccxt_history_backup_sync", lambda t, tf: rows)

    out = await main.get_history("BTC-USD", tf="1d", limit=10, provider="Yahoo Finance")
    assert out[0]["source"] == "ccxt"


@pytest.mark.asyncio
async def test_history_raises_when_both_sources_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import main

    def _yf_fails(ticker: str, tf: str):
        raise HTTPException(status_code=502, detail="No history data available")

    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", _yf_fails)
    monkeypatch.setattr(main, "_ccxt_history_backup_sync", lambda t, tf: None)

    with pytest.raises(HTTPException) as exc:
        await main.get_history("AAPL", tf="1d", limit=10, provider="Yahoo Finance")
    assert exc.value.status_code == 502
    assert "ccxt" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# /filings feed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filings_merges_and_sorts_per_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_fetch(symbol: str, limit: int):
        if symbol == "AAPL":
            return [{"symbol": "AAPL", "type": "10-Q", "date": "2026-07-31", "title": "Quarterly report", "url": None}]
        return [{"symbol": "MSFT", "type": "8-K", "date": "2026-09-02", "title": "Corporate changes", "url": None}]

    # Bypass the TTL cache so the stub is exercised directly.
    monkeypatch.setattr(filings_api, "_CACHE", {})
    monkeypatch.setattr(filings_api, "_fetch_filings_sync", _fake_fetch)

    payload = await filings_api.get_filings(symbols="AAPL,MSFT", limit=5)
    assert payload["status"] == "available"
    assert payload["count"] == 2
    dates = [row["date"] for row in payload["items"]]
    assert dates == sorted(dates, reverse=True)  # newest first across symbols


@pytest.mark.asyncio
async def test_filings_no_symbols_is_empty_success() -> None:
    payload = await filings_api.get_filings(symbols="", limit=5)
    assert payload["status"] == "available"
    assert payload["items"] == []
    assert payload["message"] == "No symbols requested"
