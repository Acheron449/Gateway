"""P3 history contract: bar caps, source fidelity, and per-bar provenance.

The gates here mirror docs/SRS.md FR-D1, FR-D2, FR-D5 and FR-D6. Every test
stubs the provider seam, so nothing reaches Yahoo or an exchange.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import main


def _bars(start: int = 1_790_000_000, count: int = 3, spacing: int = 60) -> list[dict]:
    return [
        {
            "time": start + index * spacing,
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.5 + index,
            "volume": 10.0,
        }
        for index in range(count)
    ]


def _boom(*args, **kwargs):
    raise AssertionError("ccxt must not be consulted for this request")


@pytest.mark.asyncio
async def test_limit_above_ceiling_is_refused_with_a_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-D6: over-limit requests fail closed instead of being truncated."""
    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", _boom)

    with pytest.raises(HTTPException) as exc:
        await main.get_history("AAPL", limit=main.HISTORY_MAX_BARS + 1)

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "bar_limit"
    assert exc.value.detail["max_bars"] == main.HISTORY_MAX_BARS


@pytest.mark.asyncio
async def test_non_positive_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", _boom)

    with pytest.raises(HTTPException) as exc:
        await main.get_history("AAPL", limit=0)

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "bar_limit"


@pytest.mark.asyncio
async def test_limit_at_ceiling_is_served(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = _bars(count=5)
    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", lambda ticker, tf: rows)

    out = await main.get_history("AAPL", tf="1m", limit=main.HISTORY_MAX_BARS)

    assert len(out) == len(rows)


@pytest.mark.asyncio
async def test_requested_provider_is_never_silently_replaced(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-D1/FR-D5: an unavailable named provider reports why, no substitution."""
    monkeypatch.setattr(main, "_fetch_history_alt_provider_sync", lambda *a, **k: None)
    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", _boom)

    with pytest.raises(HTTPException) as exc:
        await main.get_history("AAPL", provider="Alpaca")

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "provider_unavailable"
    assert exc.value.detail["provider"] == "Alpaca"
    assert exc.value.detail["attempted"] == ["Alpaca"]


@pytest.mark.asyncio
async def test_equity_failure_does_not_fall_through_to_ccxt(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-D1: CCXT is a crypto path only — an equity outage surfaces the reason."""
    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", _boom)
    monkeypatch.setattr(main, "_ccxt_history_backup_sync", _boom)

    with pytest.raises(HTTPException) as exc:
        await main.get_history("AAPL", tf="1d")

    assert exc.value.status_code == 502
    assert exc.value.detail["attempted"] == ["yfinance"]


@pytest.mark.asyncio
async def test_crypto_failure_does_fall_through_to_ccxt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", _boom)
    monkeypatch.setattr(main, "_ccxt_history_backup_sync", lambda ticker, tf: _bars())

    out = await main.get_history("BTC-USD", tf="1m")

    assert out
    assert {bar["source"] for bar in out} == {"ccxt"}
    assert {bar["coverage"] for bar in out} == {"crypto / 1m"}


@pytest.mark.asyncio
async def test_every_bar_carries_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-D2: provenance travels with each bar, not just with the response."""
    rows = _bars(count=3)
    monkeypatch.setattr(main, "_fetch_history_yfinance_sync", lambda ticker, tf: rows)

    out = await main.get_history("AAPL", tf="1m", limit=10)

    assert len(out) == 3
    for bar, row in zip(out, rows):
        assert bar["source"] == "yfinance"
        assert bar["provider_version"] == "yf-v1"
        assert bar["coverage"] == "US equities / 1m"
        assert bar["data_time"].startswith("20")
        assert bar["fetched_at"].startswith("20")
        assert bar["entitlement"] == "configured-provider"
    # Bars are resampled onto the 1m grid, so provenance rides on every bar
    # while prices are preserved in order.
    assert [bar["close"] for bar in out] == [row["close"] for row in rows]
    assert all(bar["time"] % 60 == 0 for bar in out)


def test_backtest_rejects_more_than_the_per_symbol_bar_cap() -> None:
    """FR-D6: a backtest payload cannot carry more than 5,000 bars per symbol."""
    from app.api.v1 import backtest

    payload = {
        "bars": [
            {"symbol": "AAPL", "time": index, "open": 1, "high": 1, "low": 1, "close": 1}
            for index in range(backtest.BACKTEST_MAX_BARS_PER_SYMBOL + 1)
        ]
    }

    with pytest.raises(ValueError) as exc:
        backtest._validate_bar_cap(payload["bars"])

    assert str(backtest.BACKTEST_MAX_BARS_PER_SYMBOL) in str(exc.value)
    assert "AAPL" in str(exc.value)
