"""Cointegration-filtered pairs strategy with a transparent synthetic book.

OHLCV-derived fills approximate capacity and spread; they are not historical
quotes or Level-2 replay. All model estimates for a decision exclude that bar.
"""
from __future__ import annotations

import math
import warnings
from statistics import fmean

from statsmodels.tools.sm_exceptions import CollinearityWarning
from typing import Any

import numpy as np
from statsmodels.tsa.stattools import coint


DEFAULT_PAIR_CONFIG: dict[str, float | int] = {
    "lookback": 60,
    "entry_z": 2.0,
    "exit_z": 0.5,
    "cointegration_pvalue": 0.05,
    "walk_forward_folds": 4,
    "spread_floor_bps": 2.0,
    "range_factor": 0.1,
    "participation_rate": 0.1,
}

SYNTHETIC_BOOK_NOTE = (
    "Synthetic OHLCV-derived execution; not historical Level-2 order-book replay. "
    "Capacity is estimated from bar volume, and modeled spread from a floor plus candle range."
)


def validate_pair_config(config: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(DEFAULT_PAIR_CONFIG)
    if config:
        result.update(config)
    try:
        result["lookback"] = int(result["lookback"])
        result["walk_forward_folds"] = int(result["walk_forward_folds"])
        for key in ("entry_z", "exit_z", "cointegration_pvalue", "spread_floor_bps", "range_factor", "participation_rate"):
            result[key] = float(result[key])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("Pair parameters must be valid numbers") from exc
    if result["lookback"] < 30:
        raise ValueError("lookback must be at least 30 bars")
    if not 1 <= result["walk_forward_folds"] <= 10:
        raise ValueError("walk_forward_folds must be between 1 and 10")
    if result["exit_z"] < 0 or result["entry_z"] <= result["exit_z"]:
        raise ValueError("z-score thresholds must satisfy 0 <= exit_z < entry_z")
    if not 0 < result["cointegration_pvalue"] < 1:
        raise ValueError("cointegration_pvalue must be between 0 and 1")
    if result["spread_floor_bps"] < 0 or result["range_factor"] < 0:
        raise ValueError("synthetic spread parameters cannot be negative")
    if not 0 < result["participation_rate"] <= 0.25:
        raise ValueError("participation_rate must be greater than 0 and no more than 0.25")
    return result


def align_pair_bars(bars_a: list[dict[str, Any]], bars_b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort, validate and align bars by epoch timestamp, retaining observed volume."""
    def keyed(bars: list[dict[str, Any]], suffix: str) -> dict[int, dict[str, Any]]:
        found: dict[int, dict[str, Any]] = {}
        for bar in bars:
            try:
                stamp = int(bar["time"])
                close = float(bar["close"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if stamp < 0 or not math.isfinite(close) or close <= 0:
                continue
            open_ = _positive(bar.get("open"), close)
            high = _positive(bar.get("high"), close)
            low = _positive(bar.get("low"), close)
            try:
                volume = float(bar.get("volume"))
            except (TypeError, ValueError):
                volume = 0.0
            if not math.isfinite(volume) or volume < 0:
                volume = 0.0
            found[stamp] = {f"time": stamp, f"open_{suffix}": open_, f"high_{suffix}": high,
                            f"low_{suffix}": low, f"close_{suffix}": close, f"volume_{suffix}": volume}
        return found

    a, b = keyed(bars_a, "a"), keyed(bars_b, "b")
    return [{**a[stamp], **b[stamp]} for stamp in sorted(a.keys() & b.keys())]


def _positive(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) and number > 0 else fallback


def fit_pair_model(prices_a: list[float], prices_b: list[float]) -> dict[str, float]:
    """Fit log(A)=intercept+beta*log(B)+residual; Engle-Granger null is no cointegration."""
    if len(prices_a) != len(prices_b) or len(prices_a) < 30:
        raise ValueError("At least 30 aligned observations are required to fit a pair")
    a = np.asarray(prices_a, dtype=float)
    b = np.asarray(prices_b, dtype=float)
    if not (np.isfinite(a).all() and np.isfinite(b).all()) or (a <= 0).any() or (b <= 0).any():
        raise ValueError("Pair prices must be finite and positive")
    log_a, log_b = np.log(a), np.log(b)
    centered_b = log_b - log_b.mean()
    variance = float(np.dot(centered_b, centered_b))
    if variance <= 1e-12:
        raise ValueError("Pair hedge ratio is undefined for a constant second leg")
    beta = float(np.dot(centered_b, log_a - log_a.mean()) / variance)
    intercept = float(log_a.mean() - beta * log_b.mean())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", CollinearityWarning)
        statistic, pvalue, _critical = coint(log_a, log_b, trend="c", method="aeg", autolag="aic")
    if not (math.isfinite(float(pvalue)) and math.isfinite(float(statistic))):
        return {"beta": beta, "intercept": intercept, "pvalue": 1.0,
                "test_statistic": float(statistic) if math.isfinite(float(statistic)) else 0.0,
                "residual_mean": float((log_a - intercept - beta * log_b).mean()),
                "residual_std": float((log_a - intercept - beta * log_b).std(ddof=1))}
    residuals = log_a - intercept - beta * log_b
    return {"beta": beta, "intercept": intercept, "pvalue": float(pvalue),
            "test_statistic": float(statistic), "residual_mean": float(residuals.mean()),
            "residual_std": float(residuals.std(ddof=1))}


def pair_signal_from_zscore(current_z: float, *, previous_z: float, current: str,
                            entry_z: float, exit_z: float) -> str:
    """Emit spread-side state only on entry threshold crossings, exit at mean band."""
    if current == "short_spread" and abs(current_z) <= exit_z:
        return "flat"
    if current == "long_spread" and abs(current_z) <= exit_z:
        return "flat"
    if current != "flat":
        return current
    if previous_z <= entry_z < current_z:
        return "short_spread"
    if previous_z >= -entry_z > current_z:
        return "long_spread"
    return "flat"


def build_pair_series(aligned: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Estimate each point strictly from the preceding lookback observations."""
    cfg = validate_pair_config(config)
    lookback = cfg["lookback"]
    rows: list[dict[str, Any]] = []
    for index, bar in enumerate(aligned):
        row: dict[str, Any] = {"time": int(bar["time"]), "spread": None, "zscore": None,
                               "beta": None, "intercept": None, "pvalue": None,
                               "cointegrated": False, "signal": "flat"}
        if index >= lookback:
            history = aligned[index - lookback:index]
            try:
                model = fit_pair_model([float(x["close_a"]) for x in history],
                                       [float(x["close_b"]) for x in history])
                spread = math.log(float(bar["close_a"])) - model["intercept"] - model["beta"] * math.log(float(bar["close_b"]))
                zscore = (spread - model["residual_mean"]) / model["residual_std"] if model["residual_std"] > 1e-12 else 0.0
                row.update({"spread": spread, "zscore": zscore, "beta": model["beta"],
                            "intercept": model["intercept"], "pvalue": model["pvalue"],
                            "cointegrated": model["pvalue"] < cfg["cointegration_pvalue"]})
            except (ValueError, np.linalg.LinAlgError):
                pass
        rows.append(row)

    position = "flat"
    previous_z = 0.0
    for row in rows:
        current_z = float(row["zscore"]) if row["zscore"] is not None else 0.0
        eligible = bool(row["cointegrated"])
        if not eligible:
            position = "flat"
        else:
            position = pair_signal_from_zscore(current_z, previous_z=previous_z,
                                               current=position, entry_z=cfg["entry_z"], exit_z=cfg["exit_z"])
        row["signal"] = position
        previous_z = current_z
    return rows


def _spread_bps(bar: dict[str, Any], leg: str, cfg: dict[str, Any]) -> float:
    open_price = float(bar[f"open_{leg}"])
    range_fraction = max(0.0, float(bar[f"high_{leg}"]) - float(bar[f"low_{leg}"])) / open_price
    return float(cfg["spread_floor_bps"]) + range_fraction * float(cfg["range_factor"]) * 10_000.0


def _fill_pair(bar: dict[str, Any], signal: str, *, equity: float, cfg: dict[str, Any],
               fee_bps: float, slippage_bps: float, beta: float = 1.0) -> dict[str, Any]:
    """Fill both legs at a future bar open, proportionally limited by observed volume."""
    if signal not in ("long_spread", "short_spread"):
        return {"status": "unfilled", "reason": "flat signal", "legs": []}
    ratio = float(cfg["participation_rate"])
    volumes = [max(0.0, float(bar.get(f"volume_{leg}") or 0.0)) for leg in ("a", "b")]
    side_a, side_b = (("short", "long") if signal == "short_spread" else ("long", "short"))
    opens = [float(bar[f"open_a"]), float(bar[f"open_b"])]
    if any(v <= 0 or not math.isfinite(v) for v in volumes + opens):
        return {"status": "unfilled", "reason": "missing price or volume capacity", "legs": []}
    beta_size = abs(beta)
    desired_notionals = [equity / (1.0 + beta_size), equity * beta_size / (1.0 + beta_size)]
    caps = [v * ratio for v in volumes]
    desired = [desired_notionals[index] / opens[index] for index in range(2)]
    capacity_ratios = [caps[index] * opens[index] / desired_notionals[index] for index in range(2)]
    fill_ratio = min(1.0, *capacity_ratios)
    if fill_ratio <= 0:
        return {"status": "unfilled", "reason": "zero synthetic book capacity", "legs": []}
    legs = []
    for leg, side, open_price, quantity in zip(("a", "b"), (side_a, side_b), opens, desired):
        modeled_bps = _spread_bps(bar, leg, cfg)
        direction = 1 if side == "long" else -1
        cost_fraction = (modeled_bps / 2.0 + float(slippage_bps)) / 10_000.0
        fill_price = open_price * (1.0 + direction * cost_fraction)
        filled_quantity = quantity * fill_ratio
        fee = fill_price * filled_quantity * fee_bps / 10_000.0
        legs.append({"symbol_leg": leg, "side": side, "requested_quantity": quantity,
                     "filled_quantity": filled_quantity, "capacity": caps[0 if leg == "a" else 1],
                     "fill_price": fill_price, "modeled_spread_bps": modeled_bps,
                     "fee": fee, "status": "filled" if fill_ratio >= 1.0 else "partial"})
    return {"status": "filled" if fill_ratio >= 1.0 else "partial",
            "fill_ratio": fill_ratio, "legs": legs}


def _run_test_segment(aligned: list[dict[str, Any]], start: int, end: int, *,
                      config: dict[str, Any], capital: float, fee_bps: float,
                      slippage_bps: float) -> dict[str, Any]:
    """Walk a held-out interval with estimates trained only on bars before each decision."""
    history = aligned[:start]
    test = aligned[start:end]
    all_rows = build_pair_series(history + test, config)
    test_rows = all_rows[len(history):]
    previous_z = float(all_rows[start - 1]["zscore"] or 0.0) if start > 0 else 0.0
    position = "flat"
    for row in test_rows:
        current_z = float(row["zscore"] or 0.0)
        if row["cointegrated"]:
            position = pair_signal_from_zscore(current_z, previous_z=previous_z, current=position,
                                               entry_z=float(config["entry_z"]), exit_z=float(config["exit_z"]))
        else:
            position = "flat"
        row["signal"] = position
        previous_z = current_z
    cash = capital
    units_a = units_b = 0.0
    active_signal = "flat"
    entry_equity = capital
    entry_time: int | None = None
    entry_spread: float | None = None
    fills: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    in_market = 0

    def marked(bar: dict[str, Any]) -> float:
        return cash + units_a * float(bar["close_a"]) + units_b * float(bar["close_b"])

    def close_position(bar: dict[str, Any], *, signal_time: int, fill_time: int,
                       exit_spread: float | None, price_field: str = "open") -> None:
        nonlocal cash, units_a, units_b, active_signal, entry_time, entry_spread
        close_fill = _liquidate_pair(bar, units_a, units_b, config=config,
                                     fee_bps=fee_bps, slippage_bps=slippage_bps,
                                     price_field=price_field)
        fills.append({"signal_time": signal_time, "fill_time": fill_time,
                      "status": close_fill["status"], "legs": close_fill["legs"],
                      "fill_reference": price_field, "reason": close_fill["reason"]})
        cash += close_fill["cash"]
        units_a, units_b = close_fill["remaining_units_a"], close_fill["remaining_units_b"]
        if abs(units_a) <= 1e-12 and abs(units_b) <= 1e-12:
            exit_equity = cash
            trades.append({"direction": active_signal, "entry_time": entry_time,
                           "entry_spread": entry_spread, "exit_time": fill_time,
                           "exit_spread": exit_spread, "entry_equity": entry_equity,
                           "exit_equity": exit_equity,
                           "pnl_pct": (exit_equity / entry_equity - 1.0) * 100.0 if entry_equity else 0.0})
            active_signal, entry_time, entry_spread = "flat", None, None

    for local_index, row in enumerate(test_rows):
        bar_index = start + local_index
        bar = aligned[bar_index]
        equity = marked(bar)
        curve.append({"time": int(bar["time"]), "equity": equity})
        target = str(row["signal"])
        if target == active_signal:
            if active_signal != "flat":
                in_market += 1
            continue
        if target != "flat" and bar_index + 1 < end:
            next_bar = aligned[bar_index + 1]
            fill = _fill_pair(next_bar, target, equity=equity, cfg=config,
                              fee_bps=fee_bps, slippage_bps=slippage_bps,
                              beta=float(row.get("beta") or 1.0))
            fills.append({"signal_time": int(bar["time"]), "fill_time": int(next_bar["time"]), **fill})
            if fill["status"] in ("filled", "partial"):
                for leg in fill["legs"]:
                    side_sign = 1 if leg["side"] == "long" else -1
                    units = leg["filled_quantity"] * side_sign
                    if leg["symbol_leg"] == "a":
                        units_a += units
                    else:
                        units_b += units
                    cash -= units * leg["fill_price"] + leg["fee"]
                active_signal = target
                entry_equity = equity
                entry_time = int(next_bar["time"])
                entry_spread = row["spread"]
        elif active_signal != "flat" and target != active_signal:
            # Reduce/close at next bar open before considering another signal.
            if bar_index + 1 < end:
                next_bar = aligned[bar_index + 1]
                close_position(next_bar, signal_time=int(bar["time"]),
                               fill_time=int(next_bar["time"]), exit_spread=row["spread"])

    if active_signal != "flat" and test:
        last = test[-1]
        close_position(last, signal_time=int(last["time"]), fill_time=int(last["time"]),
                       exit_spread=test_rows[-1]["spread"], price_field="close")
    final_equity = marked(test[-1]) if test else cash
    if curve:
        curve[-1]["equity"] = final_equity
    return {"trades": trades, "fills": fills, "equity_curve": curve,
            "final_equity": final_equity, "remaining_units": {"a": units_a, "b": units_b},
            "in_market_bars": in_market, "pair_series": test_rows}


def _liquidate_pair(bar: dict[str, Any], units_a: float, units_b: float, *,
                    config: dict[str, Any], fee_bps: float, slippage_bps: float,
                    price_field: str = "open") -> dict[str, Any]:
    """Close both legs proportionally to volume capacity, retaining any unclosed units."""
    positions = [("a", units_a), ("b", units_b)]
    capacities = [max(0.0, float(bar.get(f"volume_{leg}") or 0.0)) * float(config["participation_rate"])
                  for leg, _units in positions]
    ratios = [min(1.0, capacity / abs(units)) if units else 1.0
              for capacity, (_leg, units) in zip(capacities, positions)]
    fill_ratio = min(ratios, default=0.0)
    legs = []
    cash_delta = 0.0
    remaining = {"a": units_a, "b": units_b}
    for (leg, units), capacity in zip(positions, capacities):
        if units == 0:
            continue
        reference_price = float(bar[f"{price_field}_{leg}"])
        side = "short" if units > 0 else "long"
        direction = 1 if side == "long" else -1
        modeled_bps = _spread_bps(bar, leg, config)
        fill_price = reference_price * (1.0 + direction * (modeled_bps / 2.0 + slippage_bps) / 10_000.0)
        filled_quantity = abs(units) * fill_ratio
        signed_fill = math.copysign(filled_quantity, units)
        fee = filled_quantity * fill_price * fee_bps / 10_000.0
        cash_delta += signed_fill * fill_price - fee
        remaining[leg] = units - signed_fill
        legs.append({"symbol_leg": leg, "side": side, "requested_quantity": abs(units),
                     "filled_quantity": filled_quantity, "capacity": capacity,
                     "fill_price": fill_price, "modeled_spread_bps": modeled_bps,
                     "fee": fee, "status": "filled" if fill_ratio >= 1.0 else "partial"})
    status = "unfilled" if fill_ratio <= 0 else "filled" if fill_ratio >= 1.0 else "partial"
    return {"status": status, "legs": legs, "fill_ratio": fill_ratio,
            "remaining_units_a": remaining["a"], "remaining_units_b": remaining["b"],
            "cash": float(cash_delta), "reason": f"synthetic volume-capped {price_field}-price liquidation"}


def _segment_metrics(trades: list[dict[str, Any]], curve: list[dict[str, Any]], capital: float,
                     final_equity: float | None = None) -> dict[str, Any]:
    final = float(final_equity) if final_equity is not None else (float(curve[-1]["equity"]) if curve else capital)
    returns = [float(t["pnl_pct"]) for t in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    peak = capital
    max_dd = 0.0
    for point in curve:
        peak = max(peak, float(point["equity"]))
        if peak > 0:
            max_dd = max(max_dd, (peak - float(point["equity"])) / peak * 100)
    return {"initial_equity": round(capital, 2), "final_equity": round(final, 2),
            "total_return_pct": round((final / capital - 1) * 100, 2) if capital else 0.0,
            "trades": len(trades), "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
            "max_drawdown_pct": round(max_dd, 2)}


def run_pairs_backtest(bars_a: list[dict[str, Any]], bars_b: list[dict[str, Any]], *,
                       symbol_a: str, symbol_b: str, tf: str = "1d", capital: float = 10_000.0,
                       config: dict[str, Any] | None = None, fee_bps: float = 5.0,
                       slippage_bps: float = 5.0) -> dict[str, Any]:
    """Build a deterministic pair run and chronological walk-forward OOS reports."""
    symbol_a, symbol_b = symbol_a.strip().upper(), symbol_b.strip().upper()
    if not symbol_a or not symbol_b or symbol_a == symbol_b:
        raise ValueError("Pair symbols must be distinct and non-empty")
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("capital must be finite and positive")
    cfg = validate_pair_config(config)
    aligned = align_pair_bars(bars_a, bars_b)
    min_observations = max(2 * cfg["lookback"] + 1, 80)
    if len(aligned) < min_observations:
        raise ValueError(f"Not enough overlapping pair history ({len(aligned)} aligned bars; need {min_observations})")

    rows = build_pair_series(aligned, cfg)
    # OOS folds have a warm-up training window before each later test slice.
    fold_count = cfg["walk_forward_folds"]
    remaining = len(aligned) - cfg["lookback"]
    test_size = remaining // (fold_count + 1)
    if test_size < 10:
        raise ValueError("Not enough history for the requested walk-forward folds")
    first_test_start = len(aligned) - fold_count * test_size
    folds: list[dict[str, Any]] = []
    combined_trades: list[dict[str, Any]] = []
    combined_curve: list[dict[str, Any]] = []
    combined_fills: list[dict[str, Any]] = []
    fold_capital = capital
    for fold_index in range(fold_count):
        start = first_test_start + fold_index * test_size
        end = min(len(aligned), start + test_size)
        training = aligned[max(0, start - max(cfg["lookback"] * 4, 120)):start]
        test_model = fit_pair_model([x["close_a"] for x in training], [x["close_b"] for x in training]) if len(training) >= 30 else None
        result = _run_test_segment(aligned, start, end, config=cfg, capital=fold_capital,
                                   fee_bps=fee_bps, slippage_bps=slippage_bps)
        metrics = _segment_metrics(result["trades"], result["equity_curve"], fold_capital,
                                   final_equity=result["final_equity"])
        fold = {"fold": fold_index + 1, "train_start": int(training[0]["time"]),
                "train_end": int(training[-1]["time"]), "test_start": int(aligned[start]["time"]),
                "test_end": int(aligned[end - 1]["time"]), "train_observations": len(training),
                "test_observations": end - start, "cointegration_pvalue": test_model["pvalue"] if test_model else None,
                "cointegrated": bool(test_model and test_model["pvalue"] < cfg["cointegration_pvalue"]),
                "metrics": metrics}
        folds.append(fold)
        combined_trades.extend(result["trades"])
        combined_fills.extend(result["fills"])
        combined_curve.extend(result["equity_curve"])
        fold_capital = metrics["final_equity"]

    full_simulation = _run_test_segment(aligned, cfg["lookback"], len(aligned), config=cfg,
                                        capital=capital, fee_bps=fee_bps, slippage_bps=slippage_bps)
    full_metrics = _segment_metrics(full_simulation["trades"], full_simulation["equity_curve"], capital,
                                    final_equity=full_simulation["final_equity"])
    return {"kind": "pairs", "symbol": symbol_a, "symbol_b": symbol_b,
            "strategy": f"Cointegration pair · {symbol_a}/{symbol_b}", "tf": tf,
            "bars": len(aligned), "capital": capital, "pair_config": cfg,
            "execution_model": {"name": "synthetic_ohlcv_limit_book", "spread_floor_bps": cfg["spread_floor_bps"],
                                "range_factor": cfg["range_factor"], "participation_rate": cfg["participation_rate"],
                                "warning": SYNTHETIC_BOOK_NOTE},
            "pair_series": [{key: (round(value, 8) if isinstance(value, float) else value)
                             for key, value in row.items()} for row in rows[::max(1, len(rows) // 500)]],
            "trades": combined_trades[-500:], "fills": combined_fills[-1000:],
            "equity_curve": combined_curve[-1000:], "walk_forward": {"folds": folds,
                "out_of_sample_metrics": _aggregate_fold_metrics(folds)},
            "metrics": full_metrics, "synthetic_book_note": SYNTHETIC_BOOK_NOTE}


def _aggregate_fold_metrics(folds: list[dict[str, Any]]) -> dict[str, Any]:
    if not folds:
        return {"folds": 0, "total_return_pct": None, "trades": 0}
    returns = [float(fold["metrics"]["total_return_pct"]) for fold in folds]
    trade_count = sum(int(fold["metrics"]["trades"]) for fold in folds)
    return {"folds": len(folds), "total_return_pct": round((math.prod(1 + value / 100 for value in returns) - 1) * 100, 2),
            "mean_fold_return_pct": round(fmean(returns), 2), "trades": trade_count,
            "profitable_folds": sum(value > 0 for value in returns)}
