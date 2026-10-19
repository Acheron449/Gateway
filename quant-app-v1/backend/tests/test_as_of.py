from __future__ import annotations

from datetime import datetime, timezone
import inspect

import pytest
import httpx

from app.api.main import app, get_history
from app.models import EconomicEvent, EventImportance, NewsItem
from app.services import news_service
from app.api.nlp import sentiment
from app.providers.alltick_provider import AllTickProvider
from app.providers.alpaca_provider import AlpacaProvider
from app.providers.base import MarketDataProvider
from app.providers.ccxt_provider import CCXTProvider
from app.providers.finnhub_provider import FinnhubProvider
from app.providers.lse_provider import LSEProvider
from app.providers.tradingview_provider import TradingViewProvider
from app.providers.yahoo_provider import YahooFinanceProvider

from app.services.as_of import (
    filter_timestamped_rows,
    is_at_or_before,
    normalize_as_of,
    parse_data_timestamp,
    supports_keyword_argument,
)


AS_OF = datetime(2025, 3, 14, 16, 0, tzinfo=timezone.utc)


def test_analysis_sentiment_clock_uses_as_of_when_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def capture(
        _headline: str,
        timestamp: datetime,
        *,
        as_of: datetime | None = None,
    ) -> float:
        calls.append((timestamp, as_of))
        return 0.0

    monkeypatch.setattr(sentiment, "process_news_sentiment", capture)
    sentiment.get_latest_score_for_ticker("AAPL", as_of=AS_OF)
    assert calls == [(AS_OF, AS_OF)]


def test_parse_data_timestamp_accepts_epoch_iso_z_and_offsets_as_utc() -> None:
    assert parse_data_timestamp(AS_OF.timestamp()) == AS_OF
    assert parse_data_timestamp("2025-03-14T16:00:00Z") == AS_OF
    assert parse_data_timestamp("2025-03-14T18:00:00+02:00") == AS_OF


def test_parse_data_timestamp_rejects_missing_invalid_and_naive_values() -> None:
    assert parse_data_timestamp(None) is None
    assert parse_data_timestamp("not-a-date") is None
    assert parse_data_timestamp("2025-03-14T16:00:00") is None


def test_normalize_as_of_requires_timezone_and_normalizes_to_utc() -> None:
    from datetime import timedelta

    normalized = normalize_as_of(datetime(2025, 3, 14, 18, 0, tzinfo=timezone(timedelta(hours=2))))
    assert normalized == AS_OF
    assert normalized.tzinfo == timezone.utc
    assert normalize_as_of(None) is None
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_as_of(datetime(2025, 3, 14, 16, 0))


def test_is_at_or_before_includes_boundary_and_excludes_future() -> None:
    assert is_at_or_before("2025-03-14T16:00:00Z", AS_OF)
    assert is_at_or_before(AS_OF.timestamp() - 1, AS_OF)
    assert not is_at_or_before("2025-03-14T16:00:01Z", AS_OF)
    assert not is_at_or_before(None, AS_OF)
    assert is_at_or_before(None, None)


def test_filter_timestamped_rows_is_strict_with_cutoff_and_unchanged_without() -> None:
    rows = [
        {"time": AS_OF.timestamp() - 1, "close": 1},
        {"time": AS_OF.timestamp(), "close": 2},
        {"timestamp": "2025-03-14T16:00:01Z", "close": 3},
        {"close": 4},
        {"time": "invalid", "close": 5},
    ]

    assert filter_timestamped_rows(rows, as_of=AS_OF) == rows[:2]
    assert filter_timestamped_rows(rows, as_of=None) == rows


def test_every_history_provider_exposes_keyword_only_as_of() -> None:
    providers = (
        MarketDataProvider,
        YahooFinanceProvider,
        AlpacaProvider,
        FinnhubProvider,
        TradingViewProvider,
        AllTickProvider,
        CCXTProvider,
        LSEProvider,
    )
    for provider in providers:
        parameter = inspect.signature(provider.history).parameters["as_of"]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is None


@pytest.mark.asyncio
async def test_history_api_filters_fallback_bars_after_resampling(monkeypatch: pytest.MonkeyPatch) -> None:
    before = int(AS_OF.timestamp()) - 60
    boundary = int(AS_OF.timestamp())
    after = boundary + 60
    rows = [
        {"time": before, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"time": boundary, "open": 2, "high": 2, "low": 2, "close": 2, "volume": 1},
        {"time": after, "open": 3, "high": 3, "low": 3, "close": 3, "volume": 1},
        {"open": 4, "high": 4, "low": 4, "close": 4, "volume": 1},
    ]
    monkeypatch.setattr("app.api.main._fetch_history_yfinance_sync", lambda ticker, tf, *, as_of=None: rows)
    monkeypatch.setattr("app.api.main._ccxt_history_backup_sync", lambda ticker, tf, *, as_of=None: None)

    result = await get_history("AAPL", tf="1m", as_of=AS_OF)
    assert [row["time"] for row in result] == [before, boundary]
    assert all(row["time"] <= boundary for row in result)


def test_chart_history_normalization_rejects_naive_row_timestamps_only_with_cutoff() -> None:
    from app.api import main as api_main

    row = {
        "time": "2025-03-14T16:00:00",
        "open": 1,
        "high": 1,
        "low": 1,
        "close": 1,
        "volume": 1,
    }

    assert api_main._normalize_history_rows([row]) == [
        {
            "time": api_main._history_time_to_epoch(row["time"]),
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        }
    ]
    assert api_main._normalize_history_rows([row], as_of=AS_OF) == []


@pytest.mark.asyncio
async def test_history_api_rejects_naive_as_of_query() -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/history/AAPL?as_of=2025-03-14T16:00:00")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_history_api_preserves_no_cutoff_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"time": int(AS_OF.timestamp()), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        {"time": int(AS_OF.timestamp()) + 60, "open": 2, "high": 2, "low": 2, "close": 2, "volume": 1},
    ]
    monkeypatch.setattr("app.api.main._fetch_history_yfinance_sync", lambda ticker, tf, *, as_of=None: rows)
    result = await get_history("AAPL", tf="1m", as_of=None)
    assert [row["time"] for row in result] == [row["time"] for row in rows]


@pytest.mark.asyncio
async def test_news_service_excludes_future_timestamped_items(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        name = "Test"
        meta = {"version": "test-v1"}
        is_configured = True

        async def news(self, symbol: str, limit: int, *, as_of: datetime | None = None) -> list[NewsItem]:

            return [
                NewsItem(id="past", headline="past", source="Test", published_at=AS_OF, fetched_at=AS_OF),
                NewsItem(
                    id="future", headline="future", source="Test",
                    published_at=datetime.fromtimestamp(AS_OF.timestamp() + 1, timezone.utc),
                    fetched_at=AS_OF,
                ),
            ]

    monkeypatch.setattr(news_service, "get_provider", lambda _name: Provider())
    monkeypatch.setattr(news_service, "insert_news_item", lambda _row: None)
    monkeypatch.setattr(news_service, "store_event_snapshot", lambda *args: None)
    monkeypatch.setattr(news_service, "insert_event_tags", lambda *args: None)

    items = await news_service.fetch_and_store_news(symbol="AAPL", as_of=AS_OF)
    assert [item.id for item in items] == ["past"]


@pytest.mark.asyncio
async def test_news_cache_still_filters_records_for_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    now = news_service.time.time()
    news_service._general_fetch_state["at"] = now
    past = NewsItem(id="past-cache", headline="past", source="Test", published_at=AS_OF, fetched_at=AS_OF)
    future = NewsItem(
        id="future-cache", headline="future", source="Test",
        published_at=datetime.fromtimestamp(AS_OF.timestamp() + 1, timezone.utc), fetched_at=AS_OF,
    )

    class Provider:
        name = "Test"
        meta = {"version": "test-v1"}
        is_configured = True

    monkeypatch.setattr(news_service, "get_provider", lambda _name: Provider())
    monkeypatch.setattr(news_service, "get_news_items", lambda **kwargs: _async_result([past, future]))
    result = await news_service.fetch_and_store_news(symbol=None, as_of=AS_OF)
    assert [item.id for item in result] == ["past-cache"]
    news_service._general_fetch_state["at"] = 0.0


async def _async_result(value):
    return value


@pytest.mark.asyncio
async def test_quote_cutoff_requires_trustworthy_data_time(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        name = "Test"
        meta = {"version": "test-v1"}
        is_configured = True

        async def quote(self, _symbol: str) -> dict:
            return {
                "instrument": "AAPL",
                "last_price": 100,
                "provenance": {"source": "Test", "provider_version": "test-v1"},
            }

    monkeypatch.setattr("app.api.v1.news.get_provider", lambda _name: Provider())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/quote/AAPL", params={"provider": "Test", "as_of": AS_OF.isoformat()})
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"


@pytest.mark.asyncio
async def test_calendar_cutoff_excludes_future_events(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        name = "Test"
        meta = {"version": "test-v1"}
        is_configured = True

    async def fake_events(*, provider_name: str, limit: int, as_of: datetime | None = None):
        return [
            EconomicEvent(
                id="past", title="Past", country="US", importance=EventImportance.LOW,
                scheduled_at=AS_OF, provider_version="test-v1",
            ),
            EconomicEvent(
                id="future", title="Future", country="US", importance=EventImportance.LOW,
                scheduled_at=datetime.fromtimestamp(AS_OF.timestamp() + 1, timezone.utc),
                provider_version="test-v1",
            ),
        ]

    monkeypatch.setattr("app.api.v1.news.get_provider", lambda _name: Provider())
    monkeypatch.setattr("app.api.v1.news.fetch_and_store_economic_events", fake_events)
    async def fake_provenance(_name: str):
        return {"source": "Test"}

    monkeypatch.setattr("app.api.v1.news.get_calendar_provenance", fake_provenance)
    from app.api.v1.news import get_calendar

    result = await get_calendar(provider="Test", limit=20, as_of=AS_OF)
    assert [event["id"] for event in result.events] == ["past"]


@pytest.mark.asyncio
async def test_ohlcv_service_filters_cutoff_even_if_provider_returns_future_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd

    dates = pd.to_datetime(["2025-03-13T16:00:00Z", "2025-03-14T16:00:00Z", "2025-03-15T16:00:00Z"])
    frame = pd.DataFrame(
        {"Open": [1, 2, 3], "High": [1, 2, 3], "Low": [1, 2, 3], "Close": [1, 2, 3], "Volume": [1, 1, 1]},
        index=dates,
    )
    calls = []

    class Ticker:
        def __init__(self, _symbol: str):
            pass

        def history(self, **kwargs):
            calls.append(kwargs)
            return frame

    monkeypatch.setattr("app.services.market_data._yf", lambda: type("YF", (), {"Ticker": Ticker})())
    result = await __import__("app.services.market_data", fromlist=["fetch_ohlcv"]).fetch_ohlcv(
        "AAPL", as_of=AS_OF
    )
    assert len(result.dataframe) == 2
    assert result.dataframe.index[-1] == pd.Timestamp(AS_OF)
    assert calls[0]["end"] == AS_OF.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_calendar_cutoff_with_only_future_events_is_available_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        name = "Test"
        meta = {"version": "test-v1"}
        is_configured = True

    async def fake_events(*, provider_name: str, limit: int, as_of: datetime | None = None):
        return [
            EconomicEvent(
                id="future-only", title="Future", country="US", importance=EventImportance.LOW,
                scheduled_at=datetime.fromtimestamp(AS_OF.timestamp() + 1, timezone.utc),
                provider_version="test-v1",
            ),
        ]

    monkeypatch.setattr("app.api.v1.news.get_provider", lambda _name: Provider())
    monkeypatch.setattr("app.api.v1.news.fetch_and_store_economic_events", fake_events)

    async def fake_provenance(_name: str):
        return {"source": "Test"}

    monkeypatch.setattr("app.api.v1.news.get_calendar_provenance", fake_provenance)
    from app.api.v1.news import get_calendar

    result = await get_calendar(provider="Test", limit=20, as_of=AS_OF)
    assert result.status == "available"
    assert result.events == []
    assert result.count == 0


@pytest.mark.asyncio
async def test_ohlcv_service_rejects_naive_index_for_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd
    from app.services.market_data import fetch_ohlcv

    frame = pd.DataFrame(
        {"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]},
        index=pd.to_datetime(["2025-03-14 16:00:00"]),
    )

    class Ticker:
        def __init__(self, _symbol: str):
            pass

        def history(self, **_kwargs):
            return frame

    monkeypatch.setattr("app.services.market_data._yf", lambda: type("YF", (), {"Ticker": Ticker})())
    with pytest.raises(ValueError, match="timezone-aware"):
        await fetch_ohlcv("AAPL", as_of=AS_OF)


def test_provider_keyword_detection_supports_legacy_and_variadic_methods() -> None:
    async def legacy(limit: int = 5) -> None:
        return None

    async def modern(limit: int = 5, *, as_of: datetime | None = None) -> None:
        return None

    async def variadic(**kwargs) -> None:
        return None

    assert not supports_keyword_argument(legacy, "as_of")
    assert supports_keyword_argument(modern, "as_of")
    assert supports_keyword_argument(variadic, "as_of")


@pytest.mark.asyncio
async def test_news_service_supports_legacy_provider_signature_with_cutoff(monkeypatch: pytest.MonkeyPatch) -> None:
    class Provider:
        name = "Legacy"
        meta = {"version": "legacy-v1"}
        is_configured = True

        async def news(self, symbol: str, limit: int) -> list[NewsItem]:
            return [
                NewsItem(id="past-legacy", headline="past", source="Legacy", published_at=AS_OF, fetched_at=AS_OF),
                NewsItem(
                    id="future-legacy", headline="future", source="Legacy",
                    published_at=datetime.fromtimestamp(AS_OF.timestamp() + 1, timezone.utc), fetched_at=AS_OF,
                ),
            ]

    monkeypatch.setattr(news_service, "get_provider", lambda _name: Provider())
    monkeypatch.setattr(news_service, "insert_news_item", lambda _row: None)
    monkeypatch.setattr(news_service, "store_event_snapshot", lambda *args: None)
    monkeypatch.setattr(news_service, "insert_event_tags", lambda *args: None)

    result = await news_service.fetch_and_store_news(provider_name="Legacy", symbol="AAPL", as_of=AS_OF)
    assert [item.id for item in result] == ["past-legacy"]


@pytest.mark.asyncio
async def test_history_routes_use_provider_source_catalogue_and_omit_openbb_history(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.main import get_history_providers

    monkeypatch.setattr("app.api.main._alpaca_credentials", lambda: None)
    monkeypatch.setattr("app.api.main._finnhub_available", lambda: False)
    monkeypatch.setattr("app.api.main._alltick_available", lambda: False)
    monkeypatch.setattr("app.api.main._ccxt_available", lambda: False)
    monkeypatch.setattr("app.api.main._lse_available", lambda: False)
    route_paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/history/{ticker}" in route_paths
    assert "/openbb/equity" not in route_paths
    assert "/openbb/crypto" not in route_paths

    catalogue = await get_history_providers()
    provider_names = {item["name"] for item in catalogue["providers"]}
    assert {"Yahoo Finance", "Alpaca", "Finnhub", "TradingView", "AllTick", "CCXT"} <= provider_names
    assert "OpenBB" not in provider_names
    assert "OpenBB-Server" not in provider_names


@pytest.mark.asyncio
async def test_legacy_openbb_history_selection_uses_yahoo_not_openbb(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import main as api_main

    rows = [{"time": int(AS_OF.timestamp()), "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]
    called = []

    async def unexpected_openbb(*args, **kwargs):
        called.append((args, kwargs))
        return None

    monkeypatch.setattr(api_main, "_fetch_history_alt_provider_sync", unexpected_openbb)
    monkeypatch.setattr(api_main, "_fetch_history_yfinance_sync", lambda ticker, tf: rows)

    result = await api_main.get_history("AAPL", tf="1d", provider="OpenBB")

    assert result[0]["close"] == 1
    assert result[0]["source"] == "yfinance"
    assert called == []


def test_filter_timestamped_rows_uses_configured_timestamp_keys() -> None:
    rows = [
        {"published_at": "2025-03-14T15:59:59Z", "id": 1},
        {"published_at": "2025-03-14T16:00:01Z", "id": 2},
        {"published_at": None, "id": 3},
    ]
    assert filter_timestamped_rows(
        rows,
        as_of=AS_OF,
        timestamp_keys=("published_at",),
    ) == rows[:1]
