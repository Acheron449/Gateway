"""AI auto-trading engine.

Evaluates the user's watchlist on a cycle and places orders within the
user's own allocation limits. Decisions combine:

1. **Market data** — fresh OHLCV from the selected provider (momentum or
   mean-reversion signal with a confidence score).
2. **Learned experience (past trades)** — per-symbol win rate and realised
   PnL from the trade journal (paper *and* actual entries) scale confidence
   up or down, so the agent avoids repeating symbols it has consistently
   lost on and leans into its proven edge.
3. **Backtest results** — the average edge of recent local backtests scales
   confidence globally (a strategy that historically degraded capital
   tightens the agent's appetite).

Trades route to the paper portfolio by default. Live routing must be
explicitly enabled in the config and always respects the broker kill
switch. Every decision is written to ``ai_trading_log`` with its reason.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from app.services.database import get_connection, init_db

_SETTINGS_DIR = Path(__file__).resolve().parents[1] / "settings"
_CONFIG_FILE = _SETTINGS_DIR / "ai_trading.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "route": "paper",  # "paper" | "live"
    "symbols": ["SPY", "QQQ", "AAPL", "NVDA"],
    "strategy": "momentum",  # "momentum" | "mean_reversion"
    "max_position_notional": 1000.0,
    "confidence_threshold": 0.65,
    "use_journal_memory": True,
    "use_backtest_memory": True,
    "cycle_seconds": 60,
}

_CLAMP = lambda v: max(0.0, min(1.0, float(v)))  # noqa: E731


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_tables() -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_trading_log (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                symbol TEXT,
                action TEXT NOT NULL,
                confidence REAL,
                reason TEXT,
                price REAL,
                qty REAL,
                route TEXT,
                ok INTEGER DEFAULT 1,
                detail TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_log_ts ON ai_trading_log(ts)"
        )
        conn.commit()


def get_config() -> dict[str, Any]:
    if not _CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with _CONFIG_FILE.open("r", encoding="utf-8") as handle:
            stored = json.load(handle)
        merged = dict(DEFAULT_CONFIG)
        merged.update(stored if isinstance(stored, dict) else {})
        return merged
    except (OSError, ValueError, TypeError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    # Clamp to sane bounds — this config spends real (paper) money.
    merged["max_position_notional"] = max(10.0, float(merged["max_position_notional"]))
    merged["confidence_threshold"] = _CLAMP(merged["confidence_threshold"])
    merged["cycle_seconds"] = max(15, int(merged["cycle_seconds"]))
    merged["route"] = "live" if merged.get("route") == "live" else "paper"
    merged["strategy"] = "mean_reversion" if merged.get("strategy") == "mean_reversion" else "momentum"
    symbols = merged.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",")]
    merged["symbols"] = [str(s).upper() for s in symbols if str(s).strip()][:20]

    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = _CONFIG_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, _CONFIG_FILE)
    try:
        _CONFIG_FILE.chmod(0o600)
    except OSError:
        pass
    return merged


# --- Memory ----------------------------------------------------------------


def journal_memory(symbol: str) -> dict[str, Any]:
    """Closed-trade record for one symbol (paper + actual + manual)."""
    _ensure_tables()
    sym = symbol.upper()
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS closed,
                      SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                      COALESCE(SUM(pnl), 0) AS pnl
               FROM journal_entries
               WHERE symbol = ? AND status = 'closed'""",
            (sym,),
        ).fetchone()
    closed = int(row["closed"] or 0)
    wins = int(row["wins"] or 0)
    return {
        "closed": closed,
        "wins": wins,
        "win_rate": (wins / closed) if closed else None,
        "pnl": float(row["pnl"] or 0.0),
    }


def backtest_edge() -> Optional[float]:
    """Mean return of the most recent local backtests (None when no runs)."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                """SELECT initial_capital, final_capital FROM backtests
                   WHERE initial_capital > 0 AND final_capital IS NOT NULL
                   ORDER BY id DESC LIMIT 5"""
            ).fetchall()
    except Exception:
        return None
    edges = [
        (float(r["final_capital"]) / float(r["initial_capital"])) - 1.0
        for r in rows
        if r["initial_capital"]
    ]
    if not edges:
        return None
    return sum(edges) / len(edges)


# --- Signal ----------------------------------------------------------------


def score_symbol(closes: list[float], strategy: str) -> tuple[int, float, str]:
    """Return (signal, raw_confidence, reason) from a close-price series.

    signal: +1 long bias, -1 short/exit bias, 0 stand aside.
    """
    if len(closes) < 21:
        return 0, 0.0, "not enough history"
    last = closes[-1]
    window = closes[-20:]
    sma20 = sum(window) / len(window)

    if strategy == "mean_reversion":
        variance = sum((c - sma20) ** 2 for c in window) / len(window)
        stdev = math.sqrt(variance) or 1e-9
        z = (last - sma20) / stdev
        if z <= -1.0:
            signal = 1
        elif z >= 1.0:
            signal = -1
        else:
            signal = 0
        confidence = min(abs(z) / 3.0, 1.0)
        reason = f"mean-reversion z={z:+.2f} vs 20-bar mean"
        return signal, confidence, reason

    # momentum (default): distance of price from its 20-bar mean
    spread = last / sma20 - 1.0 if sma20 else 0.0
    if spread > 0.005:
        signal = 1
    elif spread < -0.005:
        signal = -1
    else:
        signal = 0
    confidence = min(abs(spread) * 50.0, 1.0)
    reason = f"momentum spread {spread:+.2%} vs 20-bar mean"
    return signal, confidence, reason


def apply_memory(symbol: str, confidence: float, config: dict[str, Any]) -> tuple[float, str]:
    """Scale confidence with journal + backtest experience."""
    notes: list[str] = []
    conf = confidence

    if config.get("use_journal_memory", True):
        memory = journal_memory(symbol)
        if memory["closed"] >= 3 and memory["win_rate"] is not None:
            # 0% win rate → ×0.75, 50% → ×1.0, 100% → ×1.25
            factor = 0.75 + 0.5 * memory["win_rate"]
            if memory["pnl"] < 0:
                factor *= 0.9  # losing record — extra caution
            conf *= factor
            notes.append(
                f"journal {memory['wins']}/{memory['closed']} wins "
                f"({memory['win_rate'] * 100:.0f}%), PnL {memory['pnl']:+.2f}"
            )

    if config.get("use_backtest_memory", True):
        edge = backtest_edge()
        if edge is not None:
            factor = 1.0 + max(-0.3, min(0.3, edge))
            conf *= factor
            notes.append(f"backtest edge {edge:+.1%}")

    return _CLAMP(conf), "; ".join(notes) if notes else "no memory signals yet"


# --- Execution helpers -----------------------------------------------------


def _paper_state() -> tuple[str, dict[str, Any]]:
    from app.services.database import create_portfolio, get_portfolio

    portfolio_id = "paper_default"
    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        create_portfolio(portfolio_id, "default_user")
        portfolio = get_portfolio(portfolio_id) or {}
    return portfolio_id, portfolio


def _place_paper_order(symbol: str, side: str, qty: int) -> dict[str, Any]:
    from app.models import OrderSide, OrderType
    from app.services.fill_simulator import FillSimulator
    from app.services.paper_portfolio import PaperPortfolioService

    portfolio_id, _ = _paper_state()
    service = PaperPortfolioService(portfolio_id)
    order = service.submit_order(
        instrument_id=symbol,
        side=OrderSide(side),
        order_type=OrderType.MARKET,
        qty=float(qty),
    )
    service.acknowledge_order(order.id)
    fill = FillSimulator().try_fill_order(portfolio_id, order.id)
    return {
        "order_id": order.id,
        "filled": bool(fill),
        "fill_price": fill.get("price") if fill else None,
    }


def _kill_switch_active() -> bool:
    try:
        from app.services.live_gates import get_live_gates

        return bool(get_live_gates().kill_switch.is_active())
    except Exception:
        return False


async def place_live_order_async(symbol: str, side: str, qty: int) -> dict[str, Any]:
    """Awaitable live placement (kill-switch checked)."""
    from app.api.v1.live import get_provider
    from app.models import OrderSide
    from app.services.broker_service import Order as BrokerOrder

    if _kill_switch_active():
        raise RuntimeError("Kill switch is active — live orders are blocked")

    provider = get_provider()
    order = BrokerOrder(
        symbol=symbol,
        side=OrderSide(side),
        quantity=float(qty),
        entry_price=0.0,
        order_type="market",
    )
    broker_id = await provider.place_order(order)
    if not broker_id:
        raise RuntimeError("Broker rejected the order")
    return {"order_id": broker_id, "filled": None, "fill_price": None}


# --- Cycle -----------------------------------------------------------------


def log_decision(
    symbol: str,
    action: str,
    confidence: float,
    reason: str,
    price: Optional[float] = None,
    qty: Optional[float] = None,
    route: str = "paper",
    ok: bool = True,
    detail: str = "",
) -> None:
    _ensure_tables()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO ai_trading_log
               (id, ts, symbol, action, confidence, reason, price, qty, route, ok, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                _now(),
                symbol,
                action,
                round(float(confidence), 4),
                reason,
                price,
                qty,
                route,
                1 if ok else 0,
                detail[:500],
            ),
        )
        conn.commit()


async def evaluate_symbol(symbol: str, config: dict[str, Any]) -> dict[str, Any]:
    """Decide what to do with one symbol (no side effects)."""
    from app.services.market_data import fetch_ohlcv

    result = await fetch_ohlcv(symbol, 120)
    closes = [float(c) for c in result.dataframe["Close"].tolist()]
    price = closes[-1] if closes else None

    signal, raw_conf, signal_reason = score_symbol(closes, config["strategy"])
    confidence, memory_note = apply_memory(symbol, raw_conf, config)

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": confidence,
        "price": price,
        "reason": f"{signal_reason} | {memory_note}",
    }


async def run_cycle() -> dict[str, Any]:
    """One full evaluation + execution pass over the configured symbols."""
    config = get_config()
    symbols: list[str] = config["symbols"]
    route: str = config["route"]
    results: list[dict[str, Any]] = []

    portfolio_id, portfolio = _paper_state()
    positions: dict[str, float] = {}
    if route == "paper":
        for p in portfolio.get("positions", []):
            positions[str(p.get("instrument_id", "")).upper()] = float(p.get("quantity", 0))
    else:
        try:
            from app.api.v1.live import get_provider

            for p in await get_provider().get_positions():
                positions[p.symbol.upper()] = float(p.qty)
        except Exception as exc:
            log_decision("", "error", 0.0, "live positions unavailable", route=route, ok=False, detail=str(exc))
            results.append({"error": str(exc)})
            return {"route": route, "decisions": results}

    cash = float(portfolio.get("cash") or 0.0)
    threshold = float(config["confidence_threshold"])
    max_notional = float(config["max_position_notional"])

    for symbol in symbols:
        try:
            decision = await evaluate_symbol(symbol, config)
        except Exception as exc:
            log_decision(symbol, "error", 0.0, "evaluation failed", route=route, ok=False, detail=str(exc))
            results.append({"symbol": symbol, "action": "error", "detail": str(exc)})
            continue

        signal = decision["signal"]
        confidence = decision["confidence"]
        price = decision["price"] or 0.0
        held = positions.get(symbol, 0.0)
        action = "hold"
        detail = ""

        try:
            if held > 0:
                if signal < 0:
                    qty = int(abs(held))
                    if qty > 0:
                        if route == "live":
                            await place_live_order_async(symbol, "sell", qty)
                        else:
                            _place_paper_order(symbol, "sell", qty)
                        action = "sell"
                        detail = f"closed {qty} @ ~{price:.2f}"
                    else:
                        detail = "held position too small to close"
                else:
                    detail = f"holding {held:g} — no exit signal"
            elif signal > 0 and confidence >= threshold and price > 0:
                budget = min(max_notional, cash)
                qty = int(budget * confidence / price)
                if qty >= 1 and budget >= price:
                    if route == "live":
                        await place_live_order_async(symbol, "buy", qty)
                    else:
                        _place_paper_order(symbol, "buy", qty)
                        cash -= qty * price
                    action = "buy"
                    detail = f"opened {qty} @ ~{price:.2f} (confidence {confidence:.0%})"
                else:
                    detail = (
                        f"budget {budget:.0f} too small for 1 share @ {price:.2f}"
                        if confidence >= threshold
                        else f"confidence {confidence:.0%} below {threshold:.0%} threshold"
                    )
            else:
                if signal <= 0:
                    detail = decision["reason"]
                else:
                    detail = f"confidence {confidence:.0%} below {threshold:.0%} threshold"

            log_decision(
                symbol,
                action,
                confidence,
                decision["reason"],
                price=price,
                qty=None,
                route=route,
                ok=True,
                detail=detail,
            )
            results.append(
                {
                    "symbol": symbol,
                    "action": action,
                    "confidence": round(confidence, 3),
                    "price": price,
                    "detail": detail,
                    "reason": decision["reason"],
                }
            )
        except Exception as exc:
            log_decision(symbol, action, confidence, decision["reason"], price=price, route=route, ok=False, detail=str(exc))
            results.append({"symbol": symbol, "action": "error", "detail": str(exc)})

    return {"route": route, "decisions": results, "ts": _now()}


def recent_log(limit: int = 50) -> list[dict[str, Any]]:
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_trading_log ORDER BY ts DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


# --- Background loop -------------------------------------------------------

_loop_task: Optional[asyncio.Task] = None


def is_running() -> bool:
    return _loop_task is not None and not _loop_task.done()


async def _cycle_loop() -> None:
    while True:
        config = get_config()
        if not config.get("enabled"):
            break
        try:
            await run_cycle()
        except Exception as exc:  # keep the loop alive no matter what
            log_decision("", "error", 0.0, "cycle failed", ok=False, detail=str(exc))
        await asyncio.sleep(max(15, int(config.get("cycle_seconds", 60))))


def start() -> dict[str, Any]:
    global _loop_task
    config = get_config()
    config["enabled"] = True
    save_config(config)
    if not is_running():
        _loop_task = asyncio.get_running_loop().create_task(_cycle_loop())
    return get_config()


def stop() -> dict[str, Any]:
    global _loop_task
    config = get_config()
    config["enabled"] = False
    save_config(config)
    if _loop_task is not None and not _loop_task.done():
        _loop_task.cancel()
    _loop_task = None
    return get_config()


def shutdown() -> None:
    """Cancel the loop on process exit *without* clearing the saved config,
    so an enabled AI trader resumes on the next boot."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        _loop_task.cancel()
    _loop_task = None


def status() -> dict[str, Any]:
    config = get_config()
    return {
        "running": is_running(),
        "config": config,
        "last_log": recent_log(5),
        "journal_memory": {s: journal_memory(s) for s in config["symbols"][:8]},
        "backtest_edge": backtest_edge(),
    }
