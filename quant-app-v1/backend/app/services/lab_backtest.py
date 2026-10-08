"""Agentic Trading Lab engine: strategy runs and easy-to-read performance stats.

Reference design (Open-Finance-Lab / AgenticTrading): define an agent
(strategy + model + prompt), run it over historical bars in a simulated
book, then compare it against simple baselines and buy & hold with
standardised metrics — return, risk-adjusted return (Sharpe), worst drop
(drawdown), win rate, profit factor — each labelled in plain language.

Two strategy kinds run through the same simulator:

- ``baseline`` — deterministic rules (buy & hold, SMA cross, RSI mean
  reversion); no model needed, so the lab is usable before any key exists.
- ``llm`` — a chosen provider/model is asked for a long/flat/short decision
  every N bars on a compact market window; answers are parsed tolerantly
  and fed into the same simulated book.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.services import llm_providers as llm_svc


_SETTINGS_DIR = Path(__file__).resolve().parent.parent / "settings"
_SETTINGS_FILE = _SETTINGS_DIR / "agentic_lab.json"


def _ensure_settings_dir() -> None:
    """Resolve a writable settings dir, relocating off read-only filesystems.

    Vercel excludes ``app/settings/`` (.vercelignore) and runs on a read-only
    function filesystem, so ``mkdir`` on the bundled path raises ``OSError:
    [Errno 30] Read-only file system`` and used to 500 every agent save. Fall
    back to the configured data dir (or the system temp dir) so reads degrade
    to an empty store and writes land somewhere writable.
    """
    global _SETTINGS_DIR, _SETTINGS_FILE
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        return
    except OSError:
        pass
    data_dir = os.getenv("GATEWAY_DATA_DIR", "").strip()
    base = Path(data_dir) if data_dir else Path(tempfile.gettempdir())
    _SETTINGS_DIR = base / "agentic_lab_settings"
    _SETTINGS_FILE = _SETTINGS_DIR / "agentic_lab.json"
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Unwritable everywhere: reads will return empty, writes will raise a
        # clear error rather than crashing at import/mkdir time.
        pass

MAX_RUNS = 50
DEFAULT_PROMPT = (
    "You are a systematic trader. Using only the market window provided, decide the "
    "next position: long, flat, or short. Consider trend, momentum, and volatility. "
    "Answer with JSON only: {\"action\": \"long|flat|short\", \"reason\": \"one sentence\"}."
)

BASELINES: dict[str, dict[str, Any]] = {
    "buy_hold": {
        "label": "Buy & hold",
        "detail": "Buy at the start, hold to the end — the market itself.",
    },
    "sma_cross": {
        "label": "SMA cross (10/30)",
        "detail": "Long while the 10-bar average is above the 30-bar average.",
    },
    "rsi_mean_reversion": {
        "label": "RSI mean reversion (14)",
        "detail": "Buy when RSI < 30 (oversold), exit when RSI > 55.",
    },
}

# RiskGuard-style rules (inspired by kweinmeister/agentic-trading): every
# proposed decision passes a risk gate before it can touch the book.
DEFAULT_RISK_RULES: dict[str, Any] = {
    # Largest share of equity a position may deploy (100 = fully invested).
    "max_position_pct": 100.0,
    # Circuit breaker: halt trading once peak-to-trough drawdown reaches this
    # (0 = disabled). Mirrors RiskGuard's portfolio-protection intent.
    "max_drawdown_pct": 0.0,
    # Reject short proposals when False.
    "allow_short": True,
}

RISK_RULE_META = [
    {"id": "max_position_pct", "label": "Max position size", "hint": "Cap on the share of equity a single position may deploy (100% = fully invested)", "min": 1, "max": 100, "step": 5},
    {"id": "max_drawdown_pct", "label": "Drawdown circuit breaker", "hint": "Halt trading for the rest of the run once the peak-to-trough drop reaches this % (0 = off)", "min": 0, "max": 100, "step": 5},
    {"id": "allow_short", "label": "Allow short selling", "hint": "When off, short proposals are rejected and logged by the risk guard", "min": None, "max": None, "step": None},
]


def normalize_rules(rules: dict[str, Any] | None) -> dict[str, Any]:
    """Merge caller-supplied risk rules over the defaults, clamped to sane ranges."""
    out = dict(DEFAULT_RISK_RULES)
    if isinstance(rules, dict):
        try:
            position = float(rules.get("max_position_pct", out["max_position_pct"]))
            out["max_position_pct"] = min(100.0, max(1.0, position))
        except (TypeError, ValueError):
            pass
        try:
            drawdown = float(rules.get("max_drawdown_pct", out["max_drawdown_pct"]))
            out["max_drawdown_pct"] = min(100.0, max(0.0, drawdown))
        except (TypeError, ValueError):
            pass
        if "allow_short" in rules:
            out["allow_short"] = bool(rules["allow_short"])
    return out

_PERIODS_PER_YEAR = {"1m": 12, "5m": 390 * 252 / 60 / 5, "15m": 390 * 252 / 60 / 15,
                     "30m": 390 * 252 / 60 / 30, "1h": 390 * 252 / 60, "1d": 252, "1wk": 52}


# ---------------------------------------------------------------------------
# Storage (agents + runs)
# ---------------------------------------------------------------------------

def _load() -> dict[str, Any]:
    _ensure_settings_dir()
    if not _SETTINGS_FILE.exists():
        return {"agents": [], "runs": []}
    try:
        with _SETTINGS_FILE.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            return {"agents": [], "runs": []}
        value.setdefault("agents", [])
        value.setdefault("runs", [])
        return value
    except (OSError, ValueError, TypeError):
        return {"agents": [], "runs": []}


def _save(data: dict[str, Any]) -> None:
    _ensure_settings_dir()
    temporary = _SETTINGS_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, _SETTINGS_FILE)


def list_agents() -> list[dict[str, Any]]:
    return list(_load().get("agents", []))


def save_agent(agent: dict[str, Any]) -> dict[str, Any]:
    data = _load()
    agents = data.setdefault("agents", [])
    agent_id = agent.get("id") or uuid.uuid4().hex[:10]
    record = {
        "id": agent_id,
        "name": str(agent.get("name") or "Untitled agent")[:80],
        "kind": agent.get("kind") if agent.get("kind") in ("llm", "baseline") else "llm",
        "baseline": agent.get("baseline") if agent.get("baseline") in BASELINES else None,
        "provider": agent.get("provider") or None,
        "model": agent.get("model") or None,
        "prompt": str(agent.get("prompt") or DEFAULT_PROMPT)[:6000],
        "symbol": (agent.get("symbol") or None),
        "tf": agent.get("tf") if agent.get("tf") in ("1d", "1h", "1wk") else "1d",
        "created_at": next(
            (a.get("created_at") for a in agents if a.get("id") == agent_id), None
        ) or datetime.now(timezone.utc).isoformat(),
    }
    agents = [a for a in agents if a.get("id") != agent_id]
    agents.insert(0, record)
    data["agents"] = agents[:100]
    _save(data)
    return record


def delete_agent(agent_id: str) -> bool:
    data = _load()
    agents = data.get("agents", [])
    remaining = [a for a in agents if a.get("id") != agent_id]
    if len(remaining) == len(agents):
        return False
    data["agents"] = remaining
    _save(data)
    return True


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    return list(_load().get("runs", []))[:limit]


def delete_run(run_id: str) -> bool:
    data = _load()
    runs = data.get("runs", [])
    remaining = [r for r in runs if r.get("id") != run_id]
    if len(remaining) == len(runs):
        return False
    data["runs"] = remaining
    _save(data)
    return True


def _store_run(run: dict[str, Any]) -> None:
    data = _load()
    runs = data.setdefault("runs", [])
    runs.insert(0, run)
    data["runs"] = runs[:MAX_RUNS]
    _save(data)


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

_PERIOD_BY_TF_AND_BARS = {
    "1d": lambda bars: "1y" if bars <= 260 else "2y" if bars <= 520 else "5y" if bars <= 1300 else "max",
    "1h": lambda bars: "3mo" if bars <= 60 else "6mo" if bars <= 130 else "1y" if bars <= 260 else "2y",
    "1wk": lambda bars: "1y" if bars <= 60 else "3y" if bars <= 160 else "5y" if bars <= 260 else "10y",
}
_INTERVAL_BY_TF = {"1d": "1d", "1h": "1h", "1wk": "1wk"}


async def fetch_bars(symbol: str, tf: str, limit: int) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` bars from the Yahoo provider (falls back to yfinance)."""
    from app.providers.registry import get_provider

    interval = _INTERVAL_BY_TF.get(tf, "1d")
    period = _PERIOD_BY_TF_AND_BARS.get(tf, _PERIOD_BY_TF_AND_BARS["1d"])(limit)

    rows: list[dict[str, Any]] = []
    provider = get_provider("Yahoo Finance")
    if provider is not None:
        raw = await provider.history(symbol.upper(), interval, period)
        for row in raw or []:
            if isinstance(row, dict):
                ts = row.get("time", row.get("timestamp"))
                close = row.get("close")
            else:
                ts = getattr(row, "time", None)
                close = getattr(row, "close", None)
            epoch = _to_epoch(ts)
            try:
                value = float(close)
            except (TypeError, ValueError):
                continue
            if epoch is None or not math.isfinite(value) or value <= 0:
                continue
            try:
                open_ = float(row.get("open")) if isinstance(row, dict) else float(getattr(row, "open", value))
                high = float(row.get("high")) if isinstance(row, dict) else float(getattr(row, "high", value))
                low = float(row.get("low")) if isinstance(row, dict) else float(getattr(row, "low", value))
            except (TypeError, ValueError):
                open_, high, low = value, value, value
            rows.append({"time": epoch, "open": open_, "high": high, "low": low, "close": value})
        rows.sort(key=lambda c: c["time"])

    if not rows:
        # Fallback: direct yfinance fetch (same data, no provider layer).
        import asyncio
        import yfinance as yf

        def _fetch() -> list[dict[str, Any]]:
            frame = yf.Ticker(symbol.upper()).history(period=period, interval=interval, auto_adjust=False)
            out: list[dict[str, Any]] = []
            if frame is None or frame.empty:
                return out
            for index, row in frame.iterrows():
                try:
                    close = float(row["Close"])
                except (TypeError, ValueError, KeyError):
                    continue
                if not math.isfinite(close) or close <= 0:
                    continue
                out.append({
                    "time": int(index.timestamp()),
                    "open": float(row.get("Open", close)),
                    "high": float(row.get("High", close)),
                    "low": float(row.get("Low", close)),
                    "close": close,
                })
            out.sort(key=lambda c: c["time"])
            return out

        rows = await asyncio.to_thread(_fetch)

    return rows[-max(20, min(int(limit), 2000)):] if rows else []


def _to_epoch(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    timestamp = getattr(value, "timestamp", None)
    if callable(timestamp):
        try:
            return int(timestamp())
        except (ValueError, OSError, OverflowError):
            return None
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

def _sma(values: list[float], period: int, index: int) -> Optional[float]:
    start = index - period + 1
    if start < 0:
        return None
    window = values[start : index + 1]
    return sum(window) / len(window)


def _rsi_series(values: list[float], period: int = 14) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return out
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period, len(values)):
        if i > period:
            delta = values[i] - values[i - 1]
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def baseline_targets(bars: list[dict[str, Any]], baseline: str) -> list[str]:
    closes = [float(b["close"]) for b in bars]
    targets = ["flat"] * len(bars)
    if baseline == "buy_hold":
        return ["long"] * len(bars)
    if baseline == "sma_cross":
        for i in range(len(closes)):
            fast = _sma(closes, 10, i)
            slow = _sma(closes, 30, i)
            if fast is None or slow is None:
                targets[i] = "flat"  # not enough history for the averages
            else:
                targets[i] = "long" if fast > slow else "flat"
        return targets
    if baseline == "rsi_mean_reversion":
        rsi = _rsi_series(closes, 14)
        state = "flat"
        for i in range(len(closes)):
            value = rsi[i]
            if value is None:
                continue
            if state == "flat" and value < 30:
                state = "long"
            elif state == "long" and value > 55:
                state = "flat"
            targets[i] = state
        return targets
    return targets


def _window_summary(bars: list[dict[str, Any]], upto: int, lookback: int = 40) -> str:
    start = max(0, upto - lookback + 1)
    window = bars[start : upto + 1]
    closes = [float(b["close"]) for b in window]
    lines = []
    step = max(1, len(window) // 15)  # compress long windows
    sampled = list(window[::step])
    if sampled[-1] is not window[-1]:
        sampled.append(window[-1])
    for bar in sampled:
        stamp = datetime.fromtimestamp(bar["time"], tz=timezone.utc).strftime("%Y-%m-%d")
        lines.append(f"{stamp} O:{bar['open']:.2f} H:{bar['high']:.2f} L:{bar['low']:.2f} C:{bar['close']:.2f}")
    summary = "\n".join(lines)

    all_closes = [float(b["close"]) for b in bars[: upto + 1]]
    indicators = []
    sma20 = _sma(all_closes, 20, upto)
    sma50 = _sma(all_closes, 50, upto)
    if sma20 is not None:
        indicators.append(f"SMA20={sma20:.2f}")
    if sma50 is not None:
        indicators.append(f"SMA50={sma50:.2f}")
    rsi_values = _rsi_series(all_closes, 14)
    if rsi_values[upto] is not None:
        indicators.append(f"RSI14={rsi_values[upto]:.1f}")
    if len(closes) > 1:
        change = (closes[-1] / closes[0] - 1.0) * 100.0
        indicators.append(f"window_change={change:+.2f}%")
    return f"Bars (compressed OHLC):\n{summary}\nIndicators: {', '.join(indicators) or 'n/a'}"


def _parse_action(text: str) -> Optional[str]:
    """Tolerantly extract long/flat/short from a model reply."""
    if not text:
        return None
    # 1) Any JSON object in the reply.
    for match in re.finditer(r"\{[^{}]*\}", text, re.DOTALL):
        try:
            payload = json.loads(match.group(0))
        except ValueError:
            continue
        action = str(payload.get("action") or payload.get("position") or payload.get("signal") or "").lower()
        if action in ("long", "buy", "bullish"):
            return "long"
        if action in ("short", "sell", "bearish"):
            return "short"
        if action in ("flat", "hold", "neutral", "cash", "none"):
            return "flat"
    # 2) Whole-reply keywords (strongest words win).
    lowered = text.lower()
    for word, action in (("short", "short"), ("sell", "short"), ("long", "long"), ("buy", "long")):
        if re.search(rf"\b{word}\b", lowered):
            return action
    if re.search(r"\b(hold|flat|neutral|cash|no position)\b", lowered):
        return "flat"
    return None


async def llm_targets(
    bars: list[dict[str, Any]],
    *,
    provider: str,
    model: str,
    prompt: str,
    step: int,
    symbol: str,
    tf: str,
    capital: float,
    on_progress: Optional[Callable[[int, int, str], Awaitable[None]]] = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Ask the model for a decision every ``step`` bars; returns (targets, decisions)."""
    closes = [float(b["close"]) for b in bars]
    targets = ["flat"] * len(bars)
    decisions: list[dict[str, Any]] = []
    current = "flat"
    decision_points = list(range(len(bars) - 1, -1, -step))[::-1]
    total = len(decision_points)
    equity = capital

    for count, index in enumerate(decision_points, start=1):
        if index < 30:
            continue
        # Mark the model's book to market between decisions.
        if count > 1:
            prev_index = decision_points[count - 2]
            if closes[prev_index] > 0:
                equity = equity * (closes[index] / closes[prev_index])
        market = _window_summary(bars, index)
        system = (
            f"{prompt}\n\nYou are trading {symbol} on the {tf} timeframe with "
            f"{equity:,.2f} equity. Current position: {current}. "
            "Only ever answer with the JSON object."
        )
        user = f"{market}\n\nDecide the next position (long/flat/short) as JSON."
        reply = await llm_svc.chat_once(
            provider,
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=220,
            timeout=60.0,
        )
        action = _parse_action(reply) or current
        current = action
        targets[index] = action
        for fill in range(index + 1, min(index + step, len(bars))):
            targets[fill] = action
        decisions.append({
            "index": index,
            "time": bars[index]["time"],
            "action": action,
            "reason": (reply.strip().splitlines()[0] if reply.strip() else "")[:240],
            "price": closes[index],
        })
        if on_progress:
            await on_progress(count, total, f"Decision {count}/{total}: {action.upper()} at {closes[index]:,.2f}")
    return targets, decisions


# ---------------------------------------------------------------------------
# Simulator + metrics
# ---------------------------------------------------------------------------

def _rebalance(
    cash: float,
    units: float,
    target_sign: int,
    price: float,
    fee: float,
    slippage: float,
    allocation: float = 1.0,
) -> tuple[float, float]:
    if units != 0:
        fill = price * (1.0 - slippage * (1 if units > 0 else -1))
        cash += units * fill
        cash -= abs(units) * fill * fee
        units = 0.0
    if target_sign != 0 and cash > 0 and allocation > 0:
        fill = price * (1.0 + slippage * target_sign)
        notional = cash * min(allocation, 1.0)
        units = target_sign * notional / fill
        cash -= units * fill
        cash -= abs(units) * fill * fee
    return cash, units


def simulate(
    bars: list[dict[str, Any]],
    targets: list[str],
    *,
    capital: float = 10_000.0,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run targets through a 1x long/flat/short book behind a risk guard.

    Every proposal passes the gate (position cap, short filter, drawdown
    circuit breaker) before execution — rejected or halted decisions are
    recorded as risk events, mirroring the RiskGuard approve/reject flow.
    """
    rules = normalize_rules(rules)
    fee = fee_bps / 10_000.0
    slippage = slippage_bps / 10_000.0
    allocation = rules["max_position_pct"] / 100.0
    sign_of = {"long": 1, "flat": 0, "short": -1}
    current_sign = 0
    cash, units = capital, 0.0
    equity_curve: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    risk_events: list[dict[str, Any]] = []
    entry_equity = capital
    entry_time: int | None = None
    entry_price: float | None = None
    in_market_bars = 0
    peak = capital
    halted = False
    prev_raw = "flat"

    def _close_leg(price: float, bar_time: int) -> None:
        nonlocal cash, units, current_sign, entry_equity, entry_time, entry_price
        direction = "long" if current_sign > 0 else "short"
        cash, units = _rebalance(cash, units, 0, price, fee, slippage)
        equity_now = cash
        trades.append({
            "direction": direction,
            "entry_equity": entry_equity,
            "exit_equity": equity_now,
            "pnl_pct": (equity_now / entry_equity - 1.0) * 100.0 if entry_equity else 0.0,
            "entry_time": entry_time,
            "entry_price": entry_price,
            "exit_time": bar_time,
            "exit_price": price,
        })
        current_sign = 0
        entry_time = None
        entry_price = None
        entry_equity = equity_now

    for index, bar in enumerate(bars):
        price = float(bar["close"])
        bar_time = int(bar["time"])
        raw = targets[index] if index < len(targets) else "flat"
        equity_now = cash + units * price

        # Drawdown circuit breaker — evaluated on marked-to-market equity.
        if not halted and rules["max_drawdown_pct"] > 0:
            peak = max(peak, equity_now)
            drawdown = (peak - equity_now) / peak * 100.0 if peak > 0 else 0.0
            if drawdown >= rules["max_drawdown_pct"]:
                halted = True
                if current_sign != 0:
                    _close_leg(price, bar_time)
                risk_events.append({
                    "index": index,
                    "time": bar_time,
                    "rule": "drawdown_halt",
                    "proposed": raw,
                    "approved": "flat",
                    "reason": (
                        f"Drawdown {drawdown:.1f}% reached the "
                        f"{rules['max_drawdown_pct']:.0f}% limit — trading halted for the run"
                    ),
                })

        effective = "flat" if halted else raw
        # Short filter — reject proposals when shorts are disabled.
        if effective == "short" and not rules["allow_short"]:
            effective = "flat"
            if raw != prev_raw:
                risk_events.append({
                    "index": index,
                    "time": bar_time,
                    "rule": "short_rejected",
                    "proposed": raw,
                    "approved": "flat",
                    "reason": "Short proposal rejected — short selling is disabled by the risk guard",
                })

        desired_sign = sign_of.get(effective, 0)
        if desired_sign != current_sign:
            if current_sign != 0:
                _close_leg(price, bar_time)
            if desired_sign != 0:
                cash, units = _rebalance(cash, units, desired_sign, price, fee, slippage, allocation)
                current_sign = desired_sign
                entry_equity = max(cash + units * price, 1e-9)
                entry_time = bar_time
                entry_price = price
        prev_raw = raw
        if current_sign != 0:
            in_market_bars += 1
        marked = cash + units * price
        peak = max(peak, marked)
        equity_curve.append({"time": bar_time, "equity": marked})

    # Close any open position at the end so the last leg counts as a trade.
    if current_sign != 0 and bars:
        final_price = float(bars[-1]["close"])
        _close_leg(final_price, int(bars[-1]["time"]))
    final_equity = cash + units * float(bars[-1]["close"]) if bars else capital
    if equity_curve:
        equity_curve[-1]["equity"] = final_equity

    return {
        "equity_curve": equity_curve,
        "trades": trades,
        "final_equity": final_equity,
        "in_market_bars": in_market_bars,
        "risk_events": risk_events,
        "risk_halted": halted,
        "allocation": allocation,
        "rules": rules,
    }


def compute_metrics(
    bars: list[dict[str, Any]],
    simulation: dict[str, Any],
    *,
    capital: float,
    tf: str,
) -> dict[str, Any]:
    equity_curve = simulation["equity_curve"]
    trades: list[dict[str, Any]] = simulation["trades"]
    final_equity = float(simulation["final_equity"])
    total_return = (final_equity / capital - 1.0) * 100.0

    closes = [float(b["close"]) for b in bars]
    benchmark_return = ((closes[-1] / closes[0] - 1.0) * 100.0) if len(closes) > 1 else 0.0
    excess = total_return - benchmark_return

    # Per-bar equity returns → Sharpe.
    equities = [point["equity"] for point in equity_curve]
    returns = [(b / a - 1.0) for a, b in zip(equities[:-1], equities[1:]) if a > 0]
    periods_per_year = _PERIODS_PER_YEAR.get(tf, 252)
    sharpe = 0.0
    if len(returns) > 2:
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(variance)
        if std > 1e-12:
            sharpe = mean / std * math.sqrt(periods_per_year)

    # Max drawdown (magnitude, positive %).
    peak = float("-inf")
    max_dd = 0.0
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak * 100.0)

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    gross_win = sum(t["pnl_pct"] for t in wins)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 1e-9 else (float("inf") if gross_win > 0 else 0.0)
    avg_trade = (sum(t["pnl_pct"] for t in trades) / len(trades)) if trades else 0.0
    exposure = (simulation["in_market_bars"] / len(bars) * 100.0) if bars else 0.0

    if total_return - benchmark_return > 1.0:
        verdict = f"Beat the market by {excess:.1f} pts"
        verdict_tone = "good"
    elif benchmark_return - total_return > 1.0:
        verdict = f"Lagged the market by {-excess:.1f} pts"
        verdict_tone = "bad"
    else:
        verdict = "In line with the market"
        verdict_tone = "neutral"

    if max_dd < 10:
        risk = "Mild pullbacks"
    elif max_dd < 25:
        risk = "Moderate drawdowns"
    else:
        risk = "Large drawdowns"

    metrics = {
        "total_return_pct": round(total_return, 2),
        "benchmark_return_pct": round(benchmark_return, 2),
        "excess_return_pct": round(excess, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "win_rate_pct": round(win_rate, 1),
        "trades": len(trades),
        "profit_factor": round(profit_factor, 2) if math.isfinite(profit_factor) else None,
        "avg_trade_pct": round(avg_trade, 2),
        "exposure_pct": round(exposure, 1),
        "final_equity": round(final_equity, 2),
        "verdict": verdict,
        "verdict_tone": verdict_tone,
        "risk_note": risk,
        "risk_overrides": len(simulation.get("risk_events") or []),
        "risk_halted": bool(simulation.get("risk_halted")),
        "risk_rules": simulation.get("rules") or dict(DEFAULT_RISK_RULES),
    }
    metrics["stats"] = [
        {"label": "Total return", "value": f"{total_return:+.2f}%", "hint": "Profit/loss on the starting equity"},
        {"label": "Market return", "value": f"{benchmark_return:+.2f}%", "hint": "Same period if you had just bought and held"},
        {"label": "vs Market", "value": f"{excess:+.2f} pts", "hint": "How much better/worse than buy & hold"},
        {"label": "Sharpe", "value": f"{sharpe:.2f}", "hint": "Risk-adjusted return — above 1 is good, above 2 is strong"},
        {"label": "Max drop", "value": f"{max_dd:.1f}%", "hint": "Worst peak-to-trough decline along the way"},
        {"label": "Win rate", "value": f"{win_rate:.0f}%", "hint": f"{len(wins)} of {len(trades)} trades ended green" if trades else "No trades closed"},
        {"label": "Profit factor", "value": ("∞" if profit_factor == float("inf") else f"{profit_factor:.2f}") if trades else "—", "hint": "Gross wins ÷ gross losses"},
        {"label": "Trades", "value": str(len(trades)), "hint": f"Exposed to the market {exposure:.0f}% of bars"},
        {
            "label": "Risk guard",
            "value": (
                "HALTED" if metrics["risk_halted"]
                else f"{metrics['risk_overrides']} override" + ("s" if metrics["risk_overrides"] != 1 else "")
                if metrics["risk_overrides"]
                else "clean"
            ),
            "hint": (
                "Risk guard stopped the run at the drawdown limit"
                if metrics["risk_halted"]
                else "Risk guard modified proposals (position cap / short filter / circuit breaker)"
                if metrics["risk_overrides"]
                else "No decision was modified by the risk guard"
            ),
        },
    ]
    return metrics


def downsample(curve: list[dict[str, Any]], points: int = 60) -> list[dict[str, Any]]:
    if len(curve) <= points:
        return curve
    stride = len(curve) / points
    sampled = [curve[int(i * stride)] for i in range(points)]
    if sampled[-1] != curve[-1]:
        sampled[-1] = curve[-1]
    return sampled


def build_chart(
    bars: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    risk_events: list[dict[str, Any]],
    points: int = 120,
) -> dict[str, Any]:
    """Price + SMA overlay with trade and risk markers (reference: the
    agentic-trading results figure — price action, SMAs, execution markers)."""
    closes = [float(b["close"]) for b in bars]
    sma10 = [_sma(closes, 10, i) for i in range(len(closes))]
    sma30 = [_sma(closes, 30, i) for i in range(len(closes))]

    stride = max(1, math.ceil(len(bars) / max(10, points)))
    sampled_idx = list(range(0, len(bars), stride))
    if sampled_idx and sampled_idx[-1] != len(bars) - 1:
        sampled_idx.append(len(bars) - 1)
    series = [
        {
            "t": int(bars[i]["time"]),
            "c": round(closes[i], 4),
            "s10": round(sma10[i], 4) if sma10[i] is not None else None,
            "s30": round(sma30[i], 4) if sma30[i] is not None else None,
        }
        for i in sampled_idx
    ]

    markers: list[dict[str, Any]] = []
    for trade in trades:
        direction = trade.get("direction") or "long"
        if trade.get("entry_time") is not None and trade.get("entry_price") is not None:
            markers.append({
                "t": int(trade["entry_time"]),
                "price": round(float(trade["entry_price"]), 4),
                "kind": "open_long" if direction == "long" else "open_short",
                "label": f"Open {direction}",
            })
        if trade.get("exit_time") is not None and trade.get("exit_price") is not None:
            pnl = trade.get("pnl_pct", 0.0)
            markers.append({
                "t": int(trade["exit_time"]),
                "price": round(float(trade["exit_price"]), 4),
                "kind": "close_long" if direction == "long" else "close_short",
                "label": f"Close {direction} · {pnl:+.2f}%",
            })
    for event in risk_events:
        index = int(event.get("index") or 0)
        price = closes[index] if 0 <= index < len(closes) else None
        markers.append({
            "t": int(event.get("time") or (bars[index]["time"] if 0 <= index < len(bars) else 0)),
            "price": round(price, 4) if price is not None else None,
            "kind": "risk",
            "label": f"Risk guard: {event.get('reason', '')}",
        })
    markers.sort(key=lambda marker: marker["t"])
    return {"points": series, "markers": markers}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

async def run_backtest(
    spec: dict[str, Any],
    *,
    symbol: str,
    tf: str = "1d",
    bars_limit: int = 260,
    capital: float = 10_000.0,
    max_llm_calls: int = 16,
    fee_bps: float = 5.0,
    slippage_bps: float = 5.0,
    agent_id: Optional[str] = None,
    risk: dict[str, Any] | None = None,
    on_progress: Optional[Callable[[int, int, str], Awaitable[None]]] = None,
) -> dict[str, Any]:
    """Run one lab backtest and persist the resulting run with full stats."""
    kind = spec.get("kind", "baseline")
    bars = await fetch_bars(symbol, tf, bars_limit)
    if len(bars) < 40:
        raise ValueError(f"Not enough history for {symbol} ({len(bars)} bars) — try another symbol or timeframe")

    decisions: list[dict[str, Any]] = []
    if kind == "llm":
        provider = spec.get("provider") or ""
        model = spec.get("model") or ""
        if not provider or not model:
            raise ValueError("A model strategy needs a provider and a model")
        # Validate the endpoint before the long loop so errors are immediate.
        llm_svc.resolve_endpoint(provider)
        step = max(2, math.ceil((len(bars) - 30) / max(1, int(max_llm_calls))))
        prompt_text = str(spec.get("prompt") or DEFAULT_PROMPT)
        try:
            from app.services import research_store as research

            library = research.combined_context(symbol)
            if library:
                prompt_text = f"{prompt_text}\n\nUse this saved research as background:\n{library}"
        except Exception:  # noqa: BLE001 - research context is optional enrichment
            pass
        targets, decisions = await llm_targets(
            bars,
            provider=provider,
            model=model,
            prompt=prompt_text,
            step=step,
            symbol=symbol,
            tf=tf,
            capital=capital,
            on_progress=on_progress,
        )
        strategy_label = f"{llm_svc.CATALOG_BY_ID.get(provider, {}).get('label', provider)} · {model}"
    else:
        baseline = spec.get("baseline") or "buy_hold"
        if baseline not in BASELINES:
            raise ValueError(f"Unknown baseline '{baseline}'")
        if on_progress:
            await on_progress(1, 1, f"Running {BASELINES[baseline]['label']}")
        targets = baseline_targets(bars, baseline)
        strategy_label = BASELINES[baseline]["label"]

    simulation = simulate(
        bars,
        targets,
        capital=capital,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        rules=risk,
    )
    metrics = compute_metrics(bars, simulation, capital=capital, tf=tf)

    # Attach risk outcomes to the decisions that triggered them.
    events_by_index = {event["index"]: event for event in simulation.get("risk_events", [])}
    for decision in decisions:
        event = events_by_index.get(decision.get("index"))
        if event is not None:
            decision["risk"] = {
                "rule": event["rule"],
                "proposed": event["proposed"],
                "approved": event["approved"],
                "reason": event["reason"],
            }
    chart = build_chart(bars, simulation["trades"], simulation.get("risk_events", []))

    run = {
        "id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "strategy": strategy_label,
        "baseline": spec.get("baseline") if kind == "baseline" else None,
        "provider": spec.get("provider") if kind == "llm" else None,
        "model": spec.get("model") if kind == "llm" else None,
        "prompt": str(spec.get("prompt") or "")[:2000] if kind == "llm" else None,
        "agent_id": agent_id,
        "symbol": symbol.upper(),
        "tf": tf,
        "bars": len(bars),
        "capital": capital,
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "decisions": decisions[-40:],
        "trades": simulation["trades"][-30:],
        "equity_curve": downsample(simulation["equity_curve"]),
        "chart": chart,
        "risk_rules": simulation["rules"],
        "risk_events": simulation.get("risk_events", [])[:20],
        "metrics": metrics,
    }
    _store_run(run)
    return run


def runs_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Plain-language header stats for the lab page (requirement: numeric stats)."""
    if not runs:
        return {
            "runs": 0,
            "message": "No runs yet — run a baseline or a model strategy to see performance stats.",
        }
    scored = [r for r in runs if isinstance(r.get("metrics"), dict)]
    if not scored:
        return {"runs": len(runs), "message": "Runs stored without metrics."}
    best = max(scored, key=lambda r: r["metrics"].get("total_return_pct", float("-inf")))
    llm_runs = [r for r in scored if r.get("kind") == "llm"]
    avg_llm_return = (
        round(sum(r["metrics"].get("total_return_pct", 0.0) for r in llm_runs) / len(llm_runs), 2)
        if llm_runs
        else None
    )
    beat_market = [r for r in scored if r["metrics"].get("excess_return_pct", 0) > 0]
    return {
        "runs": len(scored),
        "model_runs": len(llm_runs),
        "best_return_pct": best["metrics"].get("total_return_pct"),
        "best_strategy": best.get("strategy"),
        "best_symbol": best.get("symbol"),
        "avg_model_return_pct": avg_llm_return,
        "beat_market_count": len(beat_market),
        "beat_market_pct": round(len(beat_market) / len(scored) * 100.0, 1),
        "message": None,
    }
