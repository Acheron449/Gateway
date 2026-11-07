"""Deterministic backtest engine with a receipt (SRS FR-B1..B7).

The engine is intentionally small and pure: bars in, metrics out, no network,
no clock, no RNG. Determinism is therefore structural rather than asserted —
the same ``(spec, bars, costs, seed)`` always produces the same numbers, and
the receipt records exactly those inputs plus a hash of the data they were run
against.

Costs are explicit and applied to the fill price (half-spread + slippage) and
per trade (commission, plus the spec's per-share commission). Raising them can
only reduce net PnL, which is what the phase gate checks.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

ENGINE_VERSION = "bt-1.0.0"

DEFAULT_COSTS = {
    "commission_per_trade": 1.0,
    "half_spread_bps": 2.0,
    "slippage_bps": 2.0,
    "latency_bars": 0,
}

DEFAULT_COST_BOUNDS = {
    "commission_per_trade": (0.0, 1_000.0),
    "half_spread_bps": (0.0, 500.0),
    "slippage_bps": (0.0, 500.0),
    "latency_bars": (0, 10),
}


# --- Canonicalisation -----------------------------------------------------


def _round(value: float, places: int = 6) -> float:
    if value is None or not math.isfinite(value):
        return 0.0
    return round(float(value), places)


def canon_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def spec_hash(spec: dict) -> str:
    """Hash the parts of a spec that change the numbers."""
    keep = {
        key: spec.get(key)
        for key in ("asset_universe", "timeframe", "entry", "exit", "sizing", "invalidation", "assumptions")
    }
    return hashlib.sha256(canon_json(keep).encode("utf-8")).hexdigest()[:32]


def normalize_bars(bars: list[dict]) -> list[dict]:
    """Coerce bars to sorted, finite OHLCV rows keyed by epoch seconds."""
    cleaned: list[dict] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        raw_time = bar.get("time", bar.get("timestamp"))
        try:
            epoch = int(float(raw_time))
        except (TypeError, ValueError):
            continue
        try:
            open_, high, low, close = (float(bar[key]) for key in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) and v > 0 for v in (open_, high, low, close)):
            continue
        cleaned.append(
            {
                "time": epoch,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": float(bar.get("volume") or 0.0),
            }
        )
    cleaned.sort(key=lambda b: b["time"])
    return cleaned


def data_hash(symbol: str, timeframe: str, bars: list[dict]) -> str:
    payload = {"symbol": symbol.upper(), "timeframe": timeframe, "bars": bars}
    return hashlib.sha256(canon_json(payload).encode("utf-8")).hexdigest()


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


# --- Indicators -----------------------------------------------------------


def _sma(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if window <= 0:
        return out
    running = 0.0
    for i, value in enumerate(values):
        running += value
        if i >= window:
            running -= values[i - window]
        if i >= window - 1:
            out[i] = running / window
    return out


def _rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    return out


# --- Strategy parameters --------------------------------------------------


def resolve_params(spec: dict) -> dict[str, Any]:
    """Read the tunables out of a typed spec, with the template defaults."""
    entry = spec.get("entry") or {}
    exit_ = spec.get("exit") or {}
    sizing = spec.get("sizing") or {}
    entry_params = entry.get("params") or {}
    exit_params = exit_.get("params") or {}
    entry_condition = str(entry.get("condition") or "").lower()
    exit_condition = str(exit_.get("condition") or "").lower()

    rsi_mode = "rsi" in entry_condition or "rsi" in exit_condition
    fast = int(entry_params.get("fast", 20))
    slow = int(entry_params.get("slow", 50))
    if fast >= slow:
        fast, slow = min(fast, slow), max(fast, slow)
        if fast == slow:
            slow = fast + 1

    amount = float(sizing.get("amount", 0.95) or 0.95)
    if sizing.get("mode") == "pct_equity" and amount > 1:
        amount = amount / 100.0

    stop_loss_pct = None
    invalidation = spec.get("invalidation") or {}
    raw_stop = invalidation.get("stop_loss")
    if isinstance(raw_stop, (int, float)) and 0 < float(raw_stop) < 1:
        stop_loss_pct = float(raw_stop)

    return {
        "fast": max(2, fast),
        "slow": max(3, slow),
        "rsi_mode": rsi_mode,
        "rsi_period": int(entry_params.get("rsi_period", 14)),
        "rsi_entry": float(entry_params.get("oversold", entry_params.get("rsi_entry", 30))),
        "rsi_exit": float(exit_params.get("overbought", exit_params.get("rsi_exit", 55))),
        "position_pct": max(0.0, min(amount, 1.0)),
        "allow_short": bool(entry_params.get("allow_short", False)),
        "stop_loss_pct": stop_loss_pct,
        "commission_per_share": float((spec.get("assumptions") or {}).get("commission", 0.0) or 0.0),
    }


def _entry_signal(
    params: dict, i: int, fast: list[float | None], slow: list[float | None], rsi: list[float | None]
) -> str | None:
    """'long' / 'short' when a fresh entry triggers at bar i."""
    if params["rsi_mode"]:
        level = rsi[i]
        prev = rsi[i - 1] if i > 0 else None
        if level is None or prev is None:
            return None
        if prev >= params["rsi_entry"] > level:
            return "long"
        if params["allow_short"] and prev <= 100 - params["rsi_entry"] < level:
            return "short"
        return None

    f_now, s_now = fast[i], slow[i]
    f_prev, s_prev = fast[i - 1], slow[i - 1]
    if None in (f_now, s_now, f_prev, s_prev):
        return None
    if f_prev <= s_prev and f_now > s_now:
        return "long"
    if params["allow_short"] and f_prev >= s_prev and f_now < s_now:
        return "short"
    return None


def _exit_signal(
    params: dict, i: int, side: str, fast: list[float | None], slow: list[float | None], rsi: list[float | None]
) -> bool:
    if params["rsi_mode"]:
        level = rsi[i]
        if level is None:
            return False
        return level >= params["rsi_exit"] if side == "long" else level <= 100 - params["rsi_exit"]
    f_now, s_now = fast[i], slow[i]
    f_prev, s_prev = fast[i - 1], slow[i - 1]
    if None in (f_now, s_now, f_prev, s_prev):
        return False
    if side == "long":
        return f_prev >= s_prev and f_now < s_now
    return f_prev <= s_prev and f_now > s_now


def _costs(costs: dict) -> dict[str, float]:
    merged = dict(DEFAULT_COSTS)
    for key, value in (costs or {}).items():
        if key not in DEFAULT_COSTS or value is None:
            continue
        low, high = DEFAULT_COST_BOUNDS[key]
        merged[key] = max(low, min(float(value), high))
    merged["latency_bars"] = int(merged["latency_bars"])
    return merged


def latest_signal(spec: dict, bars: list[dict]) -> dict[str, Any]:
    """Signal for the most recent closed bar — used by the bot runner."""
    clean = normalize_bars(bars)
    params = resolve_params(spec)
    if len(clean) < max(params["slow"], params["rsi_period"]) + 2:
        return {"signal": "none", "inputs": {"bars": len(clean)}, "reason": "insufficient_history"}

    closes = [b["close"] for b in clean]
    fast = _sma(closes, params["fast"])
    slow = _sma(closes, params["slow"])
    rsi = _rsi(closes, params["rsi_period"])
    i = len(closes) - 1
    entry = _entry_signal(params, i, fast, slow, rsi)
    inputs = {
        "close": _round(closes[i]),
        "sma_fast": _round(fast[i]) if fast[i] is not None else None,
        "sma_slow": _round(slow[i]) if slow[i] is not None else None,
        "rsi": _round(rsi[i]) if rsi[i] is not None else None,
        "bar_time": iso(clean[i]["time"]),
        "bars": len(clean),
    }
    if entry:
        return {"signal": entry, "action": "enter", "inputs": inputs, "params": params}
    if _exit_signal(params, i, "long", fast, slow, rsi):
        return {"signal": "long", "action": "exit", "inputs": inputs, "params": params}
    return {"signal": "flat", "action": "hold", "inputs": inputs, "params": params}


# --- Simulation -----------------------------------------------------------


def _metrics(equity: list[float], trades: list[dict], initial_capital: float, exposure_bars: int, bars: int) -> dict:
    if not equity:
        return {
            "trades": 0, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe": 0.0,
            "sortino": 0.0, "hit_rate": 0.0, "profit_factor": 0.0, "expectancy": 0.0,
            "exposure_pct": 0.0, "turnover": 0.0, "net_pnl": 0.0,
        }
    returns = []
    for prev, cur in zip(equity, equity[1:]):
        returns.append((cur - prev) / prev if prev else 0.0)
    mean = sum(returns) / len(returns) if returns else 0.0
    variance = sum((r - mean) ** 2 for r in returns) / len(returns) if returns else 0.0
    std = math.sqrt(variance)
    downside = [r for r in returns if r < 0]
    d_mean = sum(downside) / len(downside) if downside else 0.0
    d_var = sum((r - d_mean) ** 2 for r in downside) / len(downside) if downside else 0.0
    d_std = math.sqrt(d_var)

    peak = equity[0]
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)

    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    net = equity[-1] - initial_capital

    return {
        "trades": len(trades),
        "net_pnl": _round(net, 2),
        "total_return_pct": _round((net / initial_capital) * 100 if initial_capital else 0.0),
        "max_drawdown_pct": _round(max_dd * 100),
        "sharpe": _round((mean / std) * math.sqrt(252) if std > 0 else 0.0),
        "sortino": _round((mean / d_std) * math.sqrt(252) if d_std > 0 else 0.0),
        "hit_rate": _round(len(wins) / len(trades) * 100 if trades else 0.0),
        "profit_factor": _round(gross_win / gross_loss) if gross_loss > 0 else (None if not wins else None),
        "expectancy": _round(net / len(trades), 2) if trades else 0.0,
        "exposure_pct": _round(exposure_bars / bars * 100 if bars else 0.0),
        "turnover": _round(sum(t["notional"] for t in trades) / initial_capital if initial_capital else 0.0, 2),
        "avg_bars_held": _round(sum(t["bars_held"] for t in trades) / len(trades), 2) if trades else 0.0,
    }


def _simulate(
    bars: list[dict], params: dict, costs: dict, initial_capital: float
) -> dict[str, Any]:
    closes = [b["close"] for b in bars]
    fast = _sma(closes, params["fast"])
    slow = _sma(closes, params["slow"])
    rsi = _rsi(closes, params["rsi_period"])

    cash = float(initial_capital)
    position: dict[str, Any] | None = None
    trades: list[dict] = []
    equity: list[float] = []
    exposure_bars = 0
    latency = costs["latency_bars"]
    cost_rate = (costs["half_spread_bps"] + costs["slippage_bps"]) / 10_000.0

    warmup = max(params["slow"], params["rsi_period"]) + 1
    for i in range(len(bars)):
        price = closes[i]

        if position is not None:
            exposure_bars += 1
            stop_pct = params["stop_loss_pct"]
            stopped = False
            if stop_pct:
                if position["side"] == "long" and price <= position["entry"] * (1 - stop_pct):
                    stopped = True
                elif position["side"] == "short" and price >= position["entry"] * (1 + stop_pct):
                    stopped = True
            due_exit = i >= position["entry_index"] + 1 and _exit_signal(
                params, i, position["side"], fast, slow, rsi
            )
            if stopped or due_exit:
                qty = position["qty"]
                if position["side"] == "long":
                    fill = price * (1 - cost_rate)
                    cash += qty * fill
                else:
                    fill = price * (1 + cost_rate)
                    cash -= qty * fill
                commission = costs["commission_per_trade"] + params["commission_per_share"] * qty
                cash -= commission
                entry_notional = position["qty"] * position["entry"]
                pnl = (
                    (fill - position["entry"]) * qty
                    if position["side"] == "long"
                    else (position["entry"] - fill) * qty
                ) - commission - position["entry_commission"]
                trades.append(
                    {
                        "side": position["side"],
                        "qty": _round(qty, 4),
                        "entry_time": iso(bars[position["entry_index"]]["time"]),
                        "exit_time": iso(bars[i]["time"]),
                        "entry_price": _round(position["entry"], 4),
                        "exit_price": _round(fill, 4),
                        "pnl": _round(pnl, 2),
                        "pnl_pct": _round((pnl / entry_notional) * 100 if entry_notional else 0.0, 4),
                        "commission": _round(commission + position["entry_commission"], 2),
                        "notional": _round(entry_notional, 2),
                        "bars_held": i - position["entry_index"],
                        "exit_reason": "stop_loss" if stopped else "signal",
                    }
                )
                position = None

        if position is None and i >= warmup and i + 1 < len(bars):
            signal = _entry_signal(params, i, fast, slow, rsi)
            if signal:
                exec_index = min(i + 1 + latency, len(bars) - 1)
                exec_price = closes[exec_index]
                qty = math.floor((cash * params["position_pct"]) / exec_price)
                if qty > 0:
                    entry = exec_price * (1 + cost_rate) if signal == "long" else exec_price * (1 - cost_rate)
                    notional = qty * entry
                    entry_commission = costs["commission_per_trade"] + params["commission_per_share"] * qty
                    if notional + entry_commission <= cash:
                        cash -= notional + entry_commission if signal == "long" else 0.0
                        position = {
                            "side": signal,
                            "qty": qty,
                            "entry": entry,
                            "entry_index": exec_index,
                            "entry_commission": entry_commission,
                        }
                        if signal == "short":
                            cash += qty * entry

        mark = cash
        if position is not None:
            if position["side"] == "long":
                mark += position["qty"] * price
            else:
                mark += position["qty"] * (2 * position["entry"] - price)
        equity.append(mark)

    # Close anything still open at the last bar so the run has a final number.
    if position is not None:
        price = closes[-1]
        qty = position["qty"]
        fill = price * (1 - cost_rate) if position["side"] == "long" else price * (1 + cost_rate)
        cash += qty * fill if position["side"] == "long" else -qty * fill
        commission = costs["commission_per_trade"] + params["commission_per_share"] * qty
        cash -= commission
        entry_notional = qty * position["entry"]
        pnl = (
            (fill - position["entry"]) * qty if position["side"] == "long" else (position["entry"] - fill) * qty
        ) - commission - position["entry_commission"]
        trades.append(
            {
                "side": position["side"],
                "qty": _round(qty, 4),
                "entry_time": iso(bars[position["entry_index"]]["time"]),
                "exit_time": iso(bars[-1]["time"]),
                "entry_price": _round(position["entry"], 4),
                "exit_price": _round(fill, 4),
                "pnl": _round(pnl, 2),
                "pnl_pct": _round((pnl / entry_notional) * 100 if entry_notional else 0.0, 4),
                "commission": _round(commission + position["entry_commission"], 2),
                "notional": _round(entry_notional, 2),
                "bars_held": len(bars) - 1 - position["entry_index"],
                "exit_reason": "end",
            }
        )
        equity[-1] = cash

    return {
        "trades": trades,
        "equity": [_round(v, 2) for v in equity],
        "metrics": _metrics([_round(v, 2) for v in equity], trades, initial_capital, exposure_bars, len(bars)),
    }


def run_backtest(
    *,
    spec: dict,
    bars: list[dict],
    symbol: str,
    timeframe: str,
    initial_capital: float = 100_000.0,
    costs: dict | None = None,
    seed: int = 42,
    oos_ratio: float = 0.3,
) -> dict[str, Any]:
    """Run one deterministic backtest and return results plus its receipt."""
    clean = normalize_bars(bars)
    if len(clean) < 5:
        raise ValueError("at least 5 valid bars are required")
    if initial_capital <= 0:
        raise ValueError("initial_capital must be greater than zero")

    resolved_costs = _costs(costs or {})
    params = resolve_params(spec)
    hash_ = data_hash(symbol, timeframe, clean)

    full = _simulate(clean, params, resolved_costs, float(initial_capital))

    oos_ratio = max(0.0, min(float(oos_ratio), 0.9))
    split = int(len(clean) * (1 - oos_ratio))
    warmup = max(params["slow"], params["rsi_period"]) + 2
    oos: dict[str, Any]
    is_metrics: dict[str, Any]
    if oos_ratio <= 0 or split <= warmup or len(clean) - split <= warmup:
        is_metrics = full["metrics"]
        oos = {
            "evaluated": False,
            "reason": (
                "oos_ratio was 0" if oos_ratio <= 0 else "not enough bars on each side of the split"
            ),
            "ratio": oos_ratio,
            "split_index": split,
        }
    else:
        in_sample = _simulate(clean[:split], params, resolved_costs, float(initial_capital))
        out_sample = _simulate(clean[split:], params, resolved_costs, float(initial_capital))
        is_metrics = in_sample["metrics"]
        oos = {
            "evaluated": True,
            "ratio": oos_ratio,
            "split_index": split,
            "split_time": iso(clean[split]["time"]),
            "metrics": out_sample["metrics"],
            "trades": len(out_sample["trades"]),
        }

    metrics = dict(full["metrics"])
    metrics["oos_evaluated"] = bool(oos["evaluated"])

    receipt = {
        "engine_version": ENGINE_VERSION,
        "run_mode": "single",
        "spec": spec,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "window": {"start": iso(clean[0]["time"]), "end": iso(clean[-1]["time"])},
        "bars": len(clean),
        "data_hash": hash_,
        "spec_hash": spec_hash(spec),
        "costs": resolved_costs,
        "seed": int(seed),
        "initial_capital": float(initial_capital),
        "oos_ratio": oos_ratio,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "receipt": receipt,
        "metrics": metrics,
        "is_metrics": is_metrics,
        "oos": oos,
        "trades": full["trades"],
        "equity_curve": [
            {"time": iso(bar["time"]), "equity": value} for bar, value in zip(clean, full["equity"])
        ],
        "engine_version": ENGINE_VERSION,
        "data_hash": hash_,
    }
