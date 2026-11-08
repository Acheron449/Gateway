from __future__ import annotations

import math

import numpy as np
import pytest

from app.services.pairs_backtest import (
    align_pair_bars,
    build_pair_series,
    fit_pair_model,
    pair_signal_from_zscore,
    run_pairs_backtest,
    _fill_pair,
    _liquidate_pair,
    _run_test_segment,
)


def _bars(times: list[int], closes: list[float], volumes: list[float] | None = None):
    rows = []
    for index, (stamp, close) in enumerate(zip(times, closes)):
        rows.append(
            {
                "time": stamp,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": volumes[index] if volumes is not None else 100_000.0,
            }
        )
    return rows


def test_align_pair_bars_sorts_and_keeps_only_valid_intersection():
    a = _bars([3, 1, 2, 4], [103, 101, -1, 104])
    b = _bars([4, 2, 1], [204, 202, 201])

    aligned = align_pair_bars(a, b)

    assert [bar["time"] for bar in aligned] == [1, 4]
    assert aligned[0]["close_a"] == 101
    assert aligned[0]["close_b"] == 201
    assert aligned[0]["volume_a"] == 100_000
    assert aligned[0]["volume_b"] == 100_000


def test_fit_pair_model_recovers_hedge_ratio_and_detects_cointegration():
    rng = np.random.default_rng(22)
    log_b = np.cumsum(rng.normal(0, 0.015, 500)) + math.log(100)
    stationary_noise = np.zeros(500)
    innovations = rng.normal(0, 0.012, 500)
    for index in range(1, len(stationary_noise)):
        stationary_noise[index] = 0.35 * stationary_noise[index - 1] + innovations[index]
    log_a = 0.7 + 1.4 * log_b + stationary_noise

    model = fit_pair_model(np.exp(log_a).tolist(), np.exp(log_b).tolist())

    assert model["beta"] == pytest.approx(1.4, abs=0.08)
    assert model["intercept"] == pytest.approx(0.7, abs=0.3)
    assert model["pvalue"] < 0.05


def test_fit_pair_model_rejects_independent_random_walks_as_non_cointegrated():
    rng = np.random.default_rng(901)
    log_a = np.cumsum(rng.normal(0, 0.02, 500)) + math.log(80)
    log_b = np.cumsum(rng.normal(0, 0.02, 500)) + math.log(50)

    model = fit_pair_model(np.exp(log_a).tolist(), np.exp(log_b).tolist())

    assert model["pvalue"] > 0.05


def test_pair_signal_mapping_requires_crossing_and_points_against_extreme():
    assert pair_signal_from_zscore(2.1, previous_z=1.8, current="flat", entry_z=2.0, exit_z=0.5) == "short_spread"
    assert pair_signal_from_zscore(-2.1, previous_z=-1.8, current="flat", entry_z=2.0, exit_z=0.5) == "long_spread"
    assert pair_signal_from_zscore(2.1, previous_z=2.2, current="flat", entry_z=2.0, exit_z=0.5) == "flat"
    assert pair_signal_from_zscore(0.4, previous_z=1.7, current="short_spread", entry_z=2.0, exit_z=0.5) == "flat"
    assert pair_signal_from_zscore(0.8, previous_z=1.1, current="short_spread", entry_z=2.0, exit_z=0.5) == "short_spread"


def test_pair_series_prefix_is_invariant_to_future_prices():
    rng = np.random.default_rng(3)
    log_b = np.cumsum(rng.normal(0, 0.01, 240)) + math.log(100)
    noise = np.zeros(240)
    innovations = rng.normal(0, 0.01, 240)
    for index in range(1, len(noise)):
        noise[index] = 0.4 * noise[index - 1] + innovations[index]
    log_a = 0.3 + 0.9 * log_b + noise
    times = list(range(240))
    bars_a = _bars(times, np.exp(log_a).tolist())
    bars_b = _bars(times, np.exp(log_b).tolist())
    future_changed = _bars(times, np.exp(log_a).tolist())
    for index in range(125, 240):
        future_changed[index]["close"] *= 1.7

    config = {"lookback": 60, "entry_z": 2.0, "exit_z": 0.5, "cointegration_pvalue": 0.05}
    original = build_pair_series(align_pair_bars(bars_a, bars_b), config)
    changed = build_pair_series(align_pair_bars(future_changed, bars_b), config)

    assert original[124] == changed[124]
    assert original[124] == changed[124]
    assert original[125]["beta"] == changed[125]["beta"]
    assert original[125]["spread"] != changed[125]["spread"]
    assert original[185]["beta"] != changed[185]["beta"]


def test_synthetic_book_scales_both_legs_to_tighter_capacity_and_charges_costs():
    bar = {
        "open_a": 100.0, "high_a": 102.0, "low_a": 99.0, "volume_a": 10_000,
        "open_b": 50.0, "high_b": 50.5, "low_b": 49.5, "volume_b": 100,
    }
    config = {"participation_rate": 0.1, "spread_floor_bps": 2, "range_factor": 0.1}

    fill = _fill_pair(bar, "short_spread", equity=10_000, cfg=config, fee_bps=5, slippage_bps=5)

    assert fill["status"] == "partial"
    assert fill["fill_ratio"] == pytest.approx(0.1)
    assert [leg["side"] for leg in fill["legs"]] == ["short", "long"]
    notional_a = fill["legs"][0]["filled_quantity"] * fill["legs"][0]["fill_price"]
    notional_b = fill["legs"][1]["filled_quantity"] * fill["legs"][1]["fill_price"]
    assert notional_a == pytest.approx(notional_b, rel=0.01)
    assert fill["legs"][0]["modeled_spread_bps"] > fill["legs"][1]["modeled_spread_bps"]
    assert all(leg["fee"] > 0 for leg in fill["legs"])


def test_pair_liquidation_respects_capacity_and_keeps_both_leg_ratio():
    bar = {"open_a": 100, "high_a": 102, "low_a": 99, "volume_a": 100,
           "open_b": 50, "high_b": 51, "low_b": 49, "volume_b": 1000}
    result = _liquidate_pair(bar, 1000, -2000,
                             config={"participation_rate": 0.1, "spread_floor_bps": 2, "range_factor": 0.1},
                             fee_bps=5, slippage_bps=5)
    assert result["status"] == "partial"
    assert result["remaining_units_a"] == pytest.approx(990)
    assert result["remaining_units_b"] == pytest.approx(-1980)
    assert result["fill_ratio"] == pytest.approx(0.01)
    assert [leg["filled_quantity"] for leg in result["legs"]] == pytest.approx([10, 20])
    assert len(result["legs"]) == 2


def test_forced_fold_close_keeps_unfilled_pair_exposure_in_final_equity(monkeypatch):
    aligned = []
    for index in range(35):
        volume = 0 if index == 34 else 1000
        aligned.append({"time": index, "open_a": 100, "high_a": 101, "low_a": 99, "close_a": 100,
                        "volume_a": volume, "open_b": 50, "high_b": 51, "low_b": 49,
                        "close_b": 50, "volume_b": volume})
    rows = [{"time": i, "spread": 0.0, "zscore": 2.5 if i >= 30 else 0.0, "beta": 1.0,
             "pvalue": 0.01, "cointegrated": True, "signal": "flat"}
            for i in range(35)]
    monkeypatch.setattr("app.services.pairs_backtest.build_pair_series", lambda *_args: rows)

    result = _run_test_segment(aligned, 30, 35,
                               config={"lookback": 30, "entry_z": 2, "exit_z": 0.5,
                                       "cointegration_pvalue": 0.05, "participation_rate": 0.1,
                                       "spread_floor_bps": 2, "range_factor": 0.1},
                               capital=10_000, fee_bps=5, slippage_bps=5)

    assert result["fills"][-1]["status"] == "unfilled"
    assert result["fills"][-1]["fill_reference"] == "close"
    assert result["remaining_units"]["a"] != 0
    assert result["remaining_units"]["b"] != 0
    assert result["trades"] == []
    assert result["equity_curve"][-1]["equity"] == pytest.approx(result["final_equity"])


def test_test_segment_resets_position_state_at_oos_boundary(monkeypatch):
    aligned = []
    for index in range(40):
        aligned.append({"time": index, "open_a": 100, "high_a": 101, "low_a": 99, "close_a": 100,
                        "volume_a": 1000, "open_b": 50, "high_b": 51, "low_b": 49,
                        "close_b": 50, "volume_b": 1000})
    rows = [{"time": i, "spread": 0.0, "zscore": (2.5 if i < 20 else 0.2), "beta": 1.0,
             "pvalue": 0.01, "cointegrated": True, "signal": ("short_spread" if i < 20 else "flat")}
            for i in range(40)]
    monkeypatch.setattr("app.services.pairs_backtest.build_pair_series", lambda *_args: rows)

    result = _run_test_segment(aligned, 20, 40,
                               config={"lookback": 30, "entry_z": 2, "exit_z": 0.5,
                                       "cointegration_pvalue": 0.05, "participation_rate": 0.1,
                                       "spread_floor_bps": 2, "range_factor": 0.1},
                               capital=10_000, fee_bps=5, slippage_bps=5)

    assert result["trades"] == []
    assert result["fills"] == []


def test_synthetic_book_does_not_invent_capacity_when_volume_is_missing():
    bar = {"open_a": 100, "high_a": 101, "low_a": 99, "volume_a": 0,
           "open_b": 50, "high_b": 51, "low_b": 49, "volume_b": 1000}
    result = _fill_pair(bar, "long_spread", equity=10_000,
                        cfg={"participation_rate": 0.1, "spread_floor_bps": 2, "range_factor": 0.1},
                        fee_bps=5, slippage_bps=5)
    assert result["status"] == "unfilled"
    assert result["legs"] == []


@pytest.mark.parametrize(
    "config",
    [
        {"lookback": 29},
        {"walk_forward_folds": 11},
        {"entry_z": 1.0, "exit_z": 1.0},
        {"cointegration_pvalue": 1.0},
        {"participation_rate": 0.5},
    ],
)
def test_pair_config_rejects_unsafe_ranges(config):
    from app.services.pairs_backtest import validate_pair_config

    with pytest.raises(ValueError):
        validate_pair_config(config)


def test_pair_run_rejects_duplicate_symbols():
    with pytest.raises(ValueError, match="distinct"):
        run_pairs_backtest([], [], symbol_a="SPY", symbol_b="spy")


def test_walk_forward_folds_are_chronological_and_include_synthetic_disclosure():
    rng = np.random.default_rng(77)
    log_b = np.cumsum(rng.normal(0, 0.01, 180)) + math.log(100)
    noise = np.zeros(180)
    innovations = rng.normal(0, 0.02, 180)
    for index in range(1, len(noise)):
        noise[index] = 0.25 * noise[index - 1] + innovations[index]
    log_a = 0.2 + 1.1 * log_b + noise
    times = list(range(1_700_000_000, 1_700_000_000 + 180 * 86400, 86400))
    bars_a = _bars(times, np.exp(log_a).tolist(), [1_000_000] * 180)
    bars_b = _bars(times, np.exp(log_b).tolist(), [1_000_000] * 180)
    config = {"lookback": 40, "walk_forward_folds": 3, "entry_z": 1.2, "exit_z": 0.3,
              "cointegration_pvalue": 0.2, "participation_rate": 0.1}

    result = run_pairs_backtest(bars_a, bars_b, symbol_a="AAA", symbol_b="BBB", config=config)

    folds = result["walk_forward"]["folds"]
    assert len(folds) == 3
    assert all(folds[index]["test_end"] < folds[index + 1]["test_start"] for index in range(2))
    assert all(fold["train_end"] < fold["test_start"] for fold in folds)
    assert result["kind"] == "pairs"
    assert result["pair_series"]
    assert "not historical Level-2" in result["synthetic_book_note"]
    assert result["walk_forward"]["out_of_sample_metrics"]["folds"] == 3
    assert all(math.isfinite(fold["metrics"]["final_equity"]) for fold in folds)
