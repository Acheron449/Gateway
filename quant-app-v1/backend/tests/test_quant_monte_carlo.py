"""Monte Carlo module (SRS §5.1, FR-M1..M7).

Every validation item in §5.1 is asserted here: zero-volatility collapse,
analytic moments at 50 000 paths, tail ordering, seed determinism and the two
ruin boundary cases.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid

import numpy as np
import pytest
from fastapi import HTTPException

from app.api.v1 import quant
from app.auth import User
from app.services import database, quant_monte_carlo as mc


def _user(user_id: str = "mc-alice") -> User:
    return User(id=user_id, email=f"{user_id}@example.test", subject=user_id)


def _lossy_returns(count: int = 300, seed: int = 5) -> list[float]:
    rng = np.random.default_rng(seed)
    return [float(value) for value in rng.normal(0.0002, 0.012, count)]


# --- §5.1 validation -------------------------------------------------------


def test_zero_volatility_collapses_every_path_to_the_deterministic_curve() -> None:
    result = mc.simulate(
        returns=[0.01] * 60, method="gbm", paths=200, horizon=40, seed=7
    )
    for point in result["fan"]:
        expected = 100_000.0 * 1.01 ** point["step"]
        assert point["p5"] == pytest.approx(expected, rel=1e-9)
        assert point["p95"] == pytest.approx(expected, rel=1e-9)
        assert point["p50"] == pytest.approx(expected, rel=1e-9)


def test_gbm_terminal_moments_match_the_analytic_values() -> None:
    returns = _lossy_returns(400, seed=17)
    log = np.log1p(np.asarray(returns))
    mu, sigma = float(log.mean()), float(log.std(ddof=1))
    horizon = 40
    result = mc.simulate(
        returns=returns, method="gbm", paths=50_000, horizon=horizon, seed=11
    )
    expected_mean = 100_000.0 * math.exp(mu * horizon)
    expected_sd = expected_mean * math.sqrt(math.exp(sigma**2 * horizon) - 1.0)
    assert result["terminal_summary"]["mean"] == pytest.approx(expected_mean, rel=0.01)
    assert result["terminal_summary"]["sd"] == pytest.approx(expected_sd, rel=0.02)


def test_tail_measures_are_ordered() -> None:
    result = mc.simulate(returns=_lossy_returns(), paths=5_000, horizon=50, seed=3)
    tails = result["var_cvar"]
    assert tails["var_99"] >= tails["var_95"]
    assert tails["cvar_95"] >= tails["var_95"]
    assert tails["cvar_99"] >= tails["var_99"]


def test_seed_determinism_and_hash_sensitivity() -> None:
    kwargs = dict(returns=_lossy_returns(120, seed=2), paths=2_000, horizon=30, seed=99)
    first = mc.simulate(**kwargs)
    second = mc.simulate(**kwargs)
    assert first == second
    assert first["output_hash"] == second["output_hash"]
    changed = mc.simulate(**{**kwargs, "seed": 100})
    assert changed["output_hash"] != first["output_hash"]


def test_ruin_boundaries() -> None:
    returns = _lossy_returns(200, seed=8)
    never = mc.simulate(returns=returns, paths=1_000, horizon=25, seed=4, ruin_fraction=0.0)
    assert never["ruin"]["probability"] == 0
    assert never["ruin"]["median_time_to_ruin"] is None

    always = mc.simulate(returns=returns, paths=1_000, horizon=25, seed=4, ruin_fraction=1.0)
    assert always["ruin"]["probability"] == 1.0
    assert always["ruin"]["median_time_to_ruin"] == 0


def test_response_shape_and_bounds() -> None:
    result = mc.simulate(returns=_lossy_returns(150, seed=9), paths=1_000, horizon=30, seed=1)
    assert result["engine_version"] == mc.ENGINE_VERSION
    assert len(result["data_hash"]) == 64 and len(result["output_hash"]) == 64
    assert result["seed"] == 1 and result["paths"] == 1_000 and result["horizon"] == 30
    assert result["method"] == "bootstrap" and result["block_length"] == 20
    assert len(result["fan"]) == 31
    for point in result["fan"]:
        assert point["p5"] <= point["p25"] <= point["p50"] <= point["p75"] <= point["p95"]
    assert len(result["terminal_distribution"]["counts"]) <= 60
    drawdowns = result["drawdown_distribution"]
    assert drawdowns["p50_pct"] <= drawdowns["p95_pct"] <= drawdowns["p99_pct"] <= drawdowns["worst_pct"]
    assert len(drawdowns["histogram"]["counts"]) == 24
    assert "not a forecast" in result["disclaimer"]


def test_default_run_stays_inside_the_five_second_budget() -> None:
    started = time.perf_counter()
    result = mc.simulate(returns=_lossy_returns(300, seed=12))
    elapsed = time.perf_counter() - started
    assert result["paths"] == 10_000 and result["horizon"] == 250
    assert elapsed < 5.0


def test_sizing_respects_the_budget_in_twenty_basis_point_steps() -> None:
    returns = _lossy_returns(300, seed=21)
    probe = mc.simulate(returns=returns, paths=4_000, horizon=40, seed=6)
    cvar = probe["var_cvar"]["cvar_99"]
    assert cvar > 0
    result = mc.simulate(
        returns=returns, paths=4_000, horizon=40, seed=6, risk_budget=0.72 * cvar
    )
    sizing = result["sizing"]
    assert sizing["position_multiplier"] == pytest.approx(0.7)
    assert sizing["position_multiplier"] * sizing["cvar_99"] <= sizing["risk_budget"] + 1e-6
    assert 0.0 <= sizing["position_multiplier"] <= 3.0


def test_sizing_hits_zero_when_the_budget_cannot_cover_one_step() -> None:
    result = mc.simulate(
        returns=_lossy_returns(200, seed=22), paths=1_000, horizon=30, seed=2, risk_budget=0
    )
    assert result["sizing"]["position_multiplier"] == 0.0
    assert "budget" in result["sizing"]["note"]


def test_sizing_caps_at_three_without_simulated_tail_loss() -> None:
    result = mc.simulate(
        returns=[0.001] * 120, paths=500, horizon=20, seed=2, risk_budget=1_000_000
    )
    assert result["var_cvar"]["cvar_99"] == 0
    assert result["sizing"]["position_multiplier"] == 3.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"paths": 0},
        {"paths": mc.MAX_PATHS + 1},
        {"horizon": 0},
        {"horizon": mc.MAX_HORIZON + 1},
        {"paths": 50_000, "horizon": 1_000},
        {"method": "brownian"},
        {"seed": -1},
        {"block_length": 0},
        {"ruin_fraction": 1.5},
        {"periods_per_year": 0},
        {"risk_budget": -1},
    ],
)
def test_invalid_parameters_are_rejected(kwargs) -> None:
    base = dict(returns=_lossy_returns(60, seed=3), paths=100, horizon=10)
    with pytest.raises(ValueError):
        mc.simulate(**{**base, **kwargs})


@pytest.mark.parametrize(
    "returns",
    [[], [0.1, -1.0], [0.1, float("nan")], [0.1, float("inf")]],
)
def test_invalid_series_are_rejected(returns) -> None:
    with pytest.raises(ValueError):
        mc.simulate(returns=returns, paths=100, horizon=10)


def test_equity_curve_requires_two_positive_points() -> None:
    with pytest.raises(ValueError):
        mc.simulate(equity_curve=[100_000.0], paths=100, horizon=10)
    result = mc.simulate(equity_curve=[100.0, 101.0, 99.0], paths=100, horizon=10)
    assert result["start_equity"] == 100.0
    assert result["observations"] == 2


# --- API -------------------------------------------------------------------


def _run(run_id: str, owner: str, *, with_curve: bool = True) -> None:
    curve = [50_000.0, 50_400.0, 50_100.0, 50_900.0, 51_200.0, 50_700.0]
    database.save_backtest_receipt(
        run_id=run_id,
        owner_id=owner,
        status="completed",
        symbol="AAPL",
        timeframe="1h",
        data_hash="a" * 64,
        receipt={"initial_capital": 50_000.0, "data_hash": "a" * 64},
        result={"equity_curve": [{"time": "2026-01-01", "equity": value} for value in curve]}
        if with_curve
        else {},
        metrics={"net_pnl": 700.0},
    )


def _request(**overrides) -> quant.MonteCarloRequest:
    base = dict(paths=500, horizon=25, seed=13)
    return quant.MonteCarloRequest(**{**base, **overrides})


def test_api_simulates_a_stored_run_and_echoes_its_receipt_hash() -> None:
    run_id = f"mc-{uuid.uuid4().hex[:10]}"
    _run(run_id, "mc-alice")
    response = asyncio.run(quant.monte_carlo(_request(run_id=run_id), _user("mc-alice")))
    assert response["source"] == "run"
    assert response["run_id"] == run_id
    assert response["receipt_data_hash"] == "a" * 64
    assert response["start_equity"] == 50_000.0
    assert response["horizon"] == 25


def test_api_hides_another_accounts_run() -> None:
    run_id = f"mc-{uuid.uuid4().hex[:10]}"
    _run(run_id, "mc-alice")
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(quant.monte_carlo(_request(run_id=run_id), _user("mc-bob")))
    assert excinfo.value.status_code == 404


def test_api_rejects_unknown_run_and_run_without_curve() -> None:
    with pytest.raises(HTTPException) as missing:
        asyncio.run(quant.monte_carlo(_request(run_id="nope"), _user()))
    assert missing.value.status_code == 404

    run_id = f"mc-{uuid.uuid4().hex[:10]}"
    _run(run_id, "mc-alice", with_curve=False)
    with pytest.raises(HTTPException) as empty:
        asyncio.run(quant.monte_carlo(_request(run_id=run_id), _user("mc-alice")))
    assert empty.value.status_code == 400
    assert empty.value.detail["code"] == "no_equity_curve"


def test_api_requires_exactly_one_input_source() -> None:
    with pytest.raises(HTTPException) as none:
        asyncio.run(quant.monte_carlo(_request(), _user()))
    assert none.value.status_code == 400
    with pytest.raises(HTTPException) as both:
        asyncio.run(
            quant.monte_carlo(
                _request(returns=[0.01, -0.01], equity_curve=[100.0, 101.0]), _user()
            )
        )
    assert both.value.status_code == 400


def test_api_accepts_an_explicit_series_and_maps_bad_method_to_400() -> None:
    response = asyncio.run(
        quant.monte_carlo(_request(returns=_lossy_returns(80, seed=31)), _user())
    )
    assert response["source"] == "returns"
    assert response["data_hash"]
    with pytest.raises(HTTPException) as bad:
        asyncio.run(
            quant.monte_carlo(
                _request(returns=_lossy_returns(40, seed=2), method="brownian"), _user()
            )
        )
    assert bad.value.status_code == 400
    assert "method" in bad.value.detail["message"]
