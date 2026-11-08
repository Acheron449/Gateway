"""Monte Carlo risk simulation (SRS §5.1, FR-M1..M7).

Two methods, both seeded through PCG64 so `(seed, paths, horizon, method,
block_length, data)` reproduce the same paths on every run and platform:

- ``gbm`` — fit μ and σ from the input log-returns and simulate log-normal
  paths: ``r_t = (μ − σ²/2)Δt + σ√Δt·Z_t``.
- ``bootstrap`` — stationary block bootstrap of the observed log-returns with
  expected block length ``L`` (default 20), wrap-around permitted. This keeps
  fat tails, volatility clustering and short-range autocorrelation, which is
  why it is the default for strategy runs.

Everything here is a simulation of the strategy's own past, not a forecast.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Optional

import numpy as np

ENGINE_VERSION = "mc-1.0.0"
METHODS = ("gbm", "bootstrap")
DEFAULT_METHOD = "bootstrap"
DEFAULT_PATHS = 10_000
MAX_PATHS = 50_000
DEFAULT_HORIZON = 250
MAX_HORIZON = 2_000
DEFAULT_BLOCK_LENGTH = 20
MAX_BLOCK_LENGTH = 1_000
DEFAULT_START_EQUITY = 100_000.0
DEFAULT_RUIN_FRACTION = 0.5
DEFAULT_PERIODS_PER_YEAR = 252
MAX_SIZING_MULTIPLIER = 3.0
SIZING_STEP = 0.05
# Upper bound on observed return/equity points per request. The simulated
# point guard below bounds paths × horizon; this bounds the input history too.
MAX_OBSERVATIONS = 20_000
# Upper bound on simulated points in memory; refused rather than OOM'd.
MAX_POINTS = 8_000_000
CHUNK = 4_000


def _validate_series(
    values: list[float], *, label: str, floor: float, max_length: int = MAX_OBSERVATIONS
) -> np.ndarray:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} must be a non-empty list of numbers")
    if len(values) > max_length:
        raise ValueError(f"{label} must contain at most {max_length:,} observations")
    try:
        array = np.asarray([float(value) for value in values], dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must contain only numbers") from exc
    if array.ndim != 1:
        raise ValueError(f"{label} must be one-dimensional")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{label} must contain only finite numbers")
    if np.any(array <= floor):
        raise ValueError(f"{label} must contain values greater than {floor}")
    return array


def _log_returns(
    *,
    returns: Optional[list[float]],
    equity_curve: Optional[list[float]],
    start_equity: Optional[float],
) -> tuple[np.ndarray, float]:
    """Turn simple returns or an equity curve into log-returns + E0."""
    if returns is not None:
        simple = _validate_series(returns, label="returns", floor=-1.0)
        equity = float(start_equity if start_equity is not None else DEFAULT_START_EQUITY)
        if not math.isfinite(equity) or equity <= 0:
            raise ValueError("start_equity must be a positive finite number")
        return np.log1p(simple), equity
    if equity_curve is not None:
        curve = _validate_series(equity_curve, label="equity_curve", floor=0.0)
        if curve.size < 2:
            raise ValueError("equity_curve needs at least two points")
        base = float(start_equity if start_equity is not None else curve[0])
        if not math.isfinite(base) or base <= 0:
            raise ValueError("start_equity must be a positive finite number")
        return np.diff(np.log(curve)), base
    raise ValueError("supply returns, equity_curve or run_id")


def _validate_params(
    *,
    paths: int,
    horizon: int,
    seed: int,
    method: str,
    block_length: int,
    ruin_fraction: float,
    periods_per_year: int,
    risk_budget: Optional[float],
) -> None:
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")
    if not isinstance(paths, int) or not 1 <= paths <= MAX_PATHS:
        raise ValueError(f"paths must be an integer between 1 and {MAX_PATHS}")
    if not isinstance(horizon, int) or not 1 <= horizon <= MAX_HORIZON:
        raise ValueError(f"horizon must be an integer between 1 and {MAX_HORIZON}")
    if paths * (horizon + 1) > MAX_POINTS:
        raise ValueError(
            f"paths × (horizon + 1) must be at most {MAX_POINTS} simulated points"
        )
    if not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
        raise ValueError("seed must be an integer between 0 and 2^63 - 1")
    if not isinstance(block_length, int) or not 1 <= block_length <= MAX_BLOCK_LENGTH:
        raise ValueError(f"block_length must be an integer between 1 and {MAX_BLOCK_LENGTH}")
    if not math.isfinite(ruin_fraction) or not 0.0 <= ruin_fraction <= 1.0:
        raise ValueError("ruin_fraction must be between 0 and 1 (a fraction of start equity)")
    if not isinstance(periods_per_year, int) or not 1 <= periods_per_year <= 100_000:
        raise ValueError("periods_per_year must be a positive integer")
    if risk_budget is not None and (not math.isfinite(risk_budget) or risk_budget < 0):
        raise ValueError("risk_budget must be a finite number of at least 0")


def _paths(
    log_returns: np.ndarray,
    *,
    start_equity: float,
    paths: int,
    horizon: int,
    seed: int,
    method: str,
    block_length: int,
    periods_per_year: int,
) -> np.ndarray:
    """Simulate ``paths`` × ``horizon + 1`` equity values (E0 in column 0)."""
    rng = np.random.Generator(np.random.PCG64(seed))
    values = np.empty((paths, horizon + 1), dtype=np.float64)
    values[:, 0] = start_equity

    if method == "gbm":
        mu_bar = float(log_returns.mean())
        sigma_bar = float(log_returns.std(ddof=1)) if log_returns.size > 1 else 0.0
        dt = 1.0 / periods_per_year
        mu_annual = mu_bar * periods_per_year
        sigma_annual = sigma_bar * math.sqrt(periods_per_year)
        drift = (mu_annual - 0.5 * sigma_annual**2) * dt
        vol = sigma_annual * math.sqrt(dt)
        for start in range(0, paths, CHUNK):
            stop = min(paths, start + CHUNK)
            shocks = rng.standard_normal((stop - start, horizon))
            steps = drift + vol * shocks
            values[start:stop, 1:] = start_equity * np.exp(np.cumsum(steps, axis=1))
        return values

    observations = log_returns.size
    new_block = rng.random((paths, horizon)) < (1.0 / block_length)
    starts = rng.integers(0, observations, size=(paths, horizon))
    indices = np.empty((paths, horizon), dtype=np.int64)
    indices[:, 0] = starts[:, 0]
    for step in range(1, horizon):
        np.copyto(indices[:, step], starts[:, step], where=new_block[:, step])
        np.copyto(
            indices[:, step],
            (indices[:, step - 1] + 1) % observations,
            where=~new_block[:, step],
        )
    for start in range(0, paths, CHUNK):
        stop = min(paths, start + CHUNK)
        sampled = log_returns[indices[start:stop]]
        values[start:stop, 1:] = start_equity * np.exp(np.cumsum(sampled, axis=1))
    return values


def _tail_metrics(pnl: np.ndarray, alpha: float) -> tuple[float, float]:
    """VaR/CVaR as positive losses (never negative)."""
    if alpha == 0.0 or pnl.size == 0:
        return 0.0, 0.0
    threshold = float(np.quantile(pnl, 1.0 - alpha))
    var = max(0.0, -threshold)
    tail = pnl[pnl <= threshold]
    cvar = max(var, float(np.mean(-tail))) if tail.size else var
    return var, cvar


def _sizing(cvar_99: float, risk_budget: Optional[float]) -> Optional[dict[str, Any]]:
    """FR-M7: largest 0.05-step multiplier k ≤ 3 with k·CVaR99 ≤ budget."""
    if risk_budget is None:
        return None
    if cvar_99 <= 1e-12:
        multiplier = MAX_SIZING_MULTIPLIER
        note = "No simulated 99% tail loss, so the largest multiplier applies."
    else:
        raw = risk_budget / cvar_99
        multiplier = math.floor(min(raw, MAX_SIZING_MULTIPLIER) / SIZING_STEP) * SIZING_STEP
        multiplier = round(multiplier, 2)
        if multiplier < SIZING_STEP:
            multiplier = 0.0
            note = (
                "No position multiplier keeps simulated CVaR at 99% inside the budget — "
                "the budget is below the smallest 0.05 step."
            )
        else:
            note = (
                f"A {multiplier:.2f}× multiplier keeps simulated CVaR at 99% "
                f"within the {risk_budget:,.2f} budget."
            )
    return {
        "risk_budget": round(float(risk_budget), 2),
        "position_multiplier": multiplier,
        "cvar_99": round(cvar_99, 2),
        "expected_tail_loss_at_multiplier": round(multiplier * cvar_99, 2),
        "note": note,
    }


def _output_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def simulate(
    *,
    returns: Optional[list[float]] = None,
    equity_curve: Optional[list[float]] = None,
    start_equity: Optional[float] = None,
    horizon: Optional[int] = None,
    paths: int = DEFAULT_PATHS,
    seed: int = 42,
    method: str = DEFAULT_METHOD,
    block_length: int = DEFAULT_BLOCK_LENGTH,
    ruin_fraction: float = DEFAULT_RUIN_FRACTION,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
    risk_budget: Optional[float] = None,
) -> dict[str, Any]:
    """Run one seeded Monte Carlo simulation and return every §5.1 output."""
    log_returns, equity = _log_returns(
        returns=returns, equity_curve=equity_curve, start_equity=start_equity
    )
    if horizon is None:
        horizon = min(DEFAULT_HORIZON, max(1, log_returns.size))
    _validate_params(
        paths=paths,
        horizon=horizon,
        seed=seed,
        method=method,
        block_length=block_length,
        ruin_fraction=ruin_fraction,
        periods_per_year=periods_per_year,
        risk_budget=risk_budget,
    )

    data_hash = hashlib.sha256(
        np.round(log_returns, 12).tobytes() + np.float64(equity).tobytes()
    ).hexdigest()

    values = _paths(
        log_returns,
        start_equity=equity,
        paths=paths,
        horizon=horizon,
        seed=seed,
        method=method,
        block_length=block_length,
        periods_per_year=periods_per_year,
    )

    quantiles = np.quantile(values, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0)
    fan = [
        {
            "step": step,
            "p5": round(float(quantiles[0, step]), 4),
            "p25": round(float(quantiles[1, step]), 4),
            "p50": round(float(quantiles[2, step]), 4),
            "p75": round(float(quantiles[3, step]), 4),
            "p95": round(float(quantiles[4, step]), 4),
        }
        for step in range(horizon + 1)
    ]

    terminal = values[:, -1]
    pnl = terminal - equity
    counts, edges = np.histogram(terminal, bins=60)
    terminal_histogram = {
        "bins": [round(float(edge), 4) for edge in edges],
        "counts": [int(count) for count in counts],
    }
    terminal_summary = {
        "mean": round(float(terminal.mean()), 4),
        "sd": round(float(terminal.std(ddof=1)) if paths > 1 else 0.0, 4),
    }

    peaks = np.maximum.accumulate(values, axis=1)
    drawdowns = np.where(peaks > 0, (peaks - values) / peaks, 0.0)
    max_drawdown = drawdowns.max(axis=1) * 100.0
    dd_counts, dd_edges = np.histogram(max_drawdown, bins=24)
    drawdown_distribution = {
        "p50_pct": round(float(np.quantile(max_drawdown, 0.50)), 4),
        "p95_pct": round(float(np.quantile(max_drawdown, 0.95)), 4),
        "p99_pct": round(float(np.quantile(max_drawdown, 0.99)), 4),
        "worst_pct": round(float(max_drawdown.max()), 4),
        "histogram": {
            "bins": [round(float(edge), 4) for edge in dd_edges],
            "counts": [int(count) for count in dd_counts],
        },
    }

    var_95, cvar_95 = _tail_metrics(pnl, 0.95)
    var_99, cvar_99 = _tail_metrics(pnl, 0.99)

    ruin_threshold = float(ruin_fraction) * equity
    ruined = (values <= ruin_threshold).any(axis=1)
    ruined_paths = int(ruined.sum())
    ruin = {
        "threshold": round(ruin_threshold, 2),
        "fraction_of_start": ruin_fraction,
        "probability": round(ruined_paths / paths, 6),
        "ruined_paths": ruined_paths,
        "median_time_to_ruin": (
            int(np.median(np.argmax(values[ruined] <= ruin_threshold, axis=1)))
            if ruined_paths
            else None
        ),
    }

    var_cvar = {
        "var_95": round(var_95, 2),
        "cvar_95": round(cvar_95, 2),
        "var_99": round(var_99, 2),
        "cvar_99": round(cvar_99, 2),
    }
    sizing = _sizing(cvar_99, risk_budget)

    payload = {
        "seed": seed,
        "paths": paths,
        "horizon": horizon,
        "method": method,
        "block_length": block_length if method == "bootstrap" else None,
        "start_equity": round(equity, 2),
        "periods_per_year": periods_per_year,
        "data_hash": data_hash,
        "engine_version": ENGINE_VERSION,
        "observations": int(log_returns.size),
        "fan": fan,
        "terminal_distribution": terminal_histogram,
        "terminal_summary": terminal_summary,
        "var_cvar": var_cvar,
        "drawdown_distribution": drawdown_distribution,
        "ruin": ruin,
        "sizing": sizing,
        "disclaimer": (
            "A simulation of this strategy's own past returns by resampling or fitting "
            "them. It is not a forecast and does not prove the strategy will keep working."
        ),
    }
    payload["output_hash"] = _output_hash(
        {key: value for key, value in payload.items() if key != "output_hash"}
    )
    return payload
