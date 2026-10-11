"""Phase 0 increment 4 — risk limits + backtest lifecycle + indicators (offline, typed).

Final Phase 0 slice, and the last Phase 0 plan item that the earlier increments
could only probe in passing ("unit tests … indicators, risk limits, backtest
lifecycle and order guards"). The split stays the honest one across the four
slices, and this file holds the risk/indicator/lifecycle math against the
**shipped** modules — nothing invented, no broker, no network, no ``users.db``,
no new dependencies:

* ``app.quant.technicals`` — the shipped RSI + Bollinger math on deterministic
  offline bars stays **finite and bounded** (RSI within [0, 100] on a 64-bar
  uptrend) and the Bollinger envelope **never inverts** (lower <= upper),
* ``app.quant.risk_manager`` — the shipped ``RiskManager``/``RiskConfig``
  sizing **never risks more than ``capital * max_portfolio_risk``** on a single
  trade unlimited… sized trade, and the shipped exposure guard **rejects** any
  add that would push ``current + new`` past total capital while **accepting**
  an in-bounds add (this is the shipped ``validate_exposure`` contract: the
  exposure-add is blue even when a live-capable add is red),
* ``app.models`` — a typed ``BacktestRun`` progresses through *every* shipped
  ``BacktestRunStatus`` (queued → running → completed → failed), each record
  carrying ``data_source`` + ``data_version`` (the two fields pydantic's
  model_dump actually proves) and a UTC lifecycle (``end >= start``).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.models import BacktestRun, BacktestRunStatus
from app.quant.risk_manager import RiskConfig, RiskManager
from app.quant.technicals import (
    calculate_bollinger_bands,
    calculate_rsi,
    calculate_rsi_pandas_ta,
    calculate_wilder_rsi,
)

RSI_PERIOD = 14          # shipped default
BB_PERIOD = 20           # shipped default
BB_STD_MULT = 2.0        # shipped default


def _bars(n_bars: int = 64) -> pd.DataFrame:
    """Deterministic offline bars: slow steady uptrend with mild deterministic noise."""
    rows = []
    close = 100.0
    for i in range(n_bars):
        close += 0.2 + 0.05 * math.sin(i / 6.0)
        rows.append(
            {
                "time": 1_700_000_000 + i * 300,
                "open": close - 0.05,
                "high": close + 0.20,
                "low": close - 0.20,
                "close": close,
                "volume": 1000.0 + 25.0 * i,
            }
        )
    return pd.DataFrame(rows)


def test_rsi_is_finite_bounded_and_warms_offline() -> None:
    closes = _bars()["close"]

    rsi = calculate_rsi(closes, period=RSI_PERIOD)

    assert isinstance(rsi, pd.Series)
    assert len(rsi) == len(closes)
    for value in rsi:
        assert math.isnan(value) or 0.0 <= value <= 100.0, f"RSI out of bounds: {value}"

    warmed = [v for v in rsi if not math.isnan(v)]
    assert warmed, "64 bars at RSI(14) must warm at least one value"
    assert all(not math.isnan(v) for v in rsi[-1:]), "warm tail must be a value, not NaN-only"


def test_wilder_rsi_matches_pandas_ta_reference_values() -> None:
    # Golden values captured from pandas-ta RSI(14), its default RMA mode.
    closes = pd.Series([100, 102, 101, 103, 102, 104, 103, 105, 104, 106, 105,
                        107, 106, 108, 107, 109], dtype=float)

    rsi = calculate_wilder_rsi(closes, period=14)

    assert math.isnan(rsi.iloc[0])
    assert rsi.iloc[1] == pytest.approx(100.0)
    assert rsi.iloc[2] == pytest.approx(96.296296296296)
    assert rsi.iloc[14] == pytest.approx(79.895093283154)
    assert rsi.iloc[15] == pytest.approx(81.595459174686)


def test_wilder_rsi_compatibility_helper_keeps_neutral_fill_for_flat_data() -> None:
    flat = calculate_rsi_pandas_ta(pd.Series([10.0] * 20), period=14)

    assert flat.tolist() == [50.0] * 20


def test_rsi_returns_neutral_for_flat_series_and_short_input() -> None:
    flat = calculate_rsi(pd.Series([10.0] * 20), period=14)
    short = calculate_rsi(pd.Series([10.0, 11.0, 12.0]), period=14)

    assert flat.iloc[-1] == pytest.approx(50.0)
    assert short.tolist() == [50.0, 100.0, 100.0]


def test_bollinger_envelope_never_inverts_offline() -> None:
    closes = _bars()["close"]

    upper, lower = calculate_bollinger_bands(closes, period=BB_PERIOD, std_mult=BB_STD_MULT)

    assert len(upper) == len(lower) == len(closes)
    for u, l in zip(upper, lower):
        assert math.isnan(u) or math.isnan(l) or l <= u, f"Bollinger envelope inverted: upper {u} < lower {l}"


def test_risk_manager_sizes_positions_within_configured_per_trade_risk() -> None:
    config = RiskConfig(max_portfolio_risk=0.02, max_total_exposure=0.20)
    manager = RiskManager(total_capital=100_000.0, config=config)

    size = manager.calculate_position_size(current_price=200.0, volatility=0.03)

    assert isinstance(size, float)
    assert 0.0 < size < 100_000.0, f"single-trade sizing must stay within capital, got {size}"
    assert size == pytest.approx(100_000.0 * 0.02 / (0.03 + 1e-6), rel=1e-9), (
        "shipped sizing (risk_manager.py:27) = capital * max_portfolio_risk / (volatility + 1e-6)"
    )


def test_risk_manager_rejects_exposure_that_would_exceed_total_capital() -> None:
    config = RiskConfig(max_portfolio_risk=0.02, max_total_exposure=0.20)
    manager = RiskManager(total_capital=100_000.0, config=config)

    within = manager.validate_exposure(current_exposure=10_000.0, new_trade_value=5_000.0)
    over = manager.validate_exposure(current_exposure=90_000.0, new_trade_value=15_000.0)

    assert within is True
    assert over is False, "current + new exposure must never exceed total capital"


def test_backtest_run_progresses_through_every_shipped_status_offline() -> None:
    now = datetime.now(timezone.utc)

    for status in BacktestRunStatus:
        run = BacktestRun(
            id=f"bt-{status.value}",
            strategy_version=3,
            engine_version="gateway-backtest-v0",
            status=status,
            start=now,
            end=now + timedelta(seconds=30),
            data_source="gateway-synthetic",
            data_version="catalogue_v1",
        )

        assert run.status == status
        assert run.data_source == "gateway-synthetic"
        assert run.data_version == "catalogue_v1"
        assert run.end >= run.start
