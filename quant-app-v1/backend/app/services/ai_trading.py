"""AI auto-trading engine, scoped to the signed-in account.

Evaluates the owner's watchlist on a cycle and places orders within that
owner's own allocation limits. Decisions combine:

1. **Market data** — fresh OHLCV from the selected provider (momentum or
   mean-reversion signal with a confidence score).
2. **Learned experience (past trades)** — per-symbol win rate and realised
   PnL from the owner's trade journal, so the agent avoids repeating symbols
   it has consistently lost on and leans into its proven edge.
3. **Backtest results** — the average edge of that owner's recent backtest
   receipts scales confidence globally.

Trades route only to ``paper_<owner_id>``. Every decision is written to
``ai_trading_log`` with its owner and reason. Configuration lives in
``ai_trading_config``; a pre-ownership JSON file and legacy ownerless rows are
never read, so an older deployment cannot leak one account's settings or
history into another's.
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.services.database import get_connection, init_db

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "route": "paper",  # live routing is not available; kept for response shape
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
    from app.services.journal_log import ensure_journal_tables

    ensure_journal_tables()
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_trading_config (
                owner_id TEXT PRIMARY KEY,
                config TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_trading_log (
                id TEXT PRIMARY KEY,
                owner_id TEXT,
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
        # Pre-ownership logs have no owner column. Add it as nullable so legacy
        # rows stay invisible (SRS DR-6/DR-7).
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_trading_log)")}
        if "owner_id" not in columns:
            conn.execute("ALTER TABLE ai_trading_log ADD COLUMN owner_id TEXT")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_log_owner ON ai_trading_log(owner_id, ts DESC)"
        )
        conn.commit()


def _normalized(config: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_CONFIG)
    merged.update(config)
    merged["max_position_notional"] = max(10.0, float(merged["max_position_notional"]))
    merged["confidence_threshold"] = _CLAMP(merged["confidence_threshold"])
    merged["cycle_seconds"] = max(15, int(merged["cycle_seconds"]))
    # Live routing was removed with the live-execution scope; old saved values
    # cannot re-enable it.
    merged["route"] = "paper"
    merged["strategy"] = "mean_reversion" if merged.get("strategy") == "mean_reversion" else "momentum"
    symbols = merged.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",")]
    merged["symbols"] = [str(s).upper() for s in symbols if str(s).strip()][:20]
    return merged


def get_config(owner_id: str) -> dict[str, Any]:
    _ensure_tables()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT config FROM ai_trading_config WHERE owner_id = ?", (owner_id,)
        ).fetchone()
    merged = dict(DEFAULT_CONFIG)
    if row:
        try:
            stored = json.loads(row["config"])
        except (TypeError, ValueError):
            stored = None
        if isinstance(stored, dict):
            merged.update(stored)
    merged["route"] = "paper"
    return merged


def save_config(owner_id: str, config: dict[str, Any]) -> dict[str, Any]:
    merged = _normalized(config)
    _ensure_tables()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO ai_trading_config (owner_id, config, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(owner_id) DO UPDATE SET
                 config = excluded.config,
                 updated_at = excluded.updated_at""",
            (owner_id, json.dumps(merged, sort_keys=True), _now()),
        )
        conn.commit()
    return merged


def enabled_owners() -> list[str]:
    """Owners whose agent was left enabled, for process-start resumption."""
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute("SELECT owner_id, config FROM ai_trading_config").fetchall()
    owners: list[str] = []
    for row in rows:
        try:
            config = json.loads(row["config"])
        except (TypeError, ValueError):
            continue
        if isinstance(config, dict) and config.get("enabled"):
            owners.append(str(row["owner_id"]))
    return owners


# --- Memory ----------------------------------------------------------------


def journal_memory(owner_id: str, symbol: str) -> dict[str, Any]:
    """Closed-trade record for one symbol from the owner's journal only."""
    _ensure_tables()
    sym = symbol.upper()
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS closed,
                      SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                      COALESCE(SUM(pnl), 0) AS pnl
               FROM journal_entries
               WHERE owner_id = ? AND symbol = ? AND status = 'closed'""",
            (owner_id, sym),
        ).fetchone()
    closed = int(row["closed"] or 0)
    wins = int(row["wins"] or 0)
    return {
        "closed": closed,
        "wins": wins,
        "win_rate": (wins / closed) if closed else None,
        "pnl": float(row["pnl"] or 0.0),
    }


def backtest_edge(owner_id: str) -> Optional[float]:
    """Mean return of the owner's most recent receipts (None when no runs)."""
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT metrics FROM backtest_receipts
               WHERE owner_id = ? AND metrics IS NOT NULL
               ORDER BY created_at DESC, rowid DESC LIMIT 5""",
            (owner_id,),
        ).fetchall()
    edges: list[float] = []
    for row in rows:
        try:
            metrics = json.loads(row["metrics"])
        except (TypeError, ValueError):
            continue
        if not isinstance(metrics, dict):
            continue
        pct = metrics.get("total_return_pct")
        if isinstance(pct, (int, float)):
            edges.append(float(pct) / 100.0)
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


def apply_memory(
    owner_id: str, symbol: str, confidence: float, config: dict[str, Any]
) -> tuple[float, str]:
    """Scale confidence with the owner's journal + backtest experience."""
    notes: list[str] = []
    conf = confidence

    if config.get("use_journal_memory", True):
        memory = journal_memory(owner_id, symbol)
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
        edge = backtest_edge(owner_id)
        if edge is not None:
            factor = 1.0 + max(-0.3, min(0.3, edge))
            conf *= factor
            notes.append(f"backtest edge {edge:+.1%}")

    return _CLAMP(conf), "; ".join(notes) if notes else "no memory signals yet"


# --- Execution helpers -----------------------------------------------------


def _paper_state(owner_id: str) -> tuple[str, dict[str, Any]]:
    from app.services.database import create_portfolio, get_portfolio

    portfolio_id = f"paper_{owner_id}"
    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        create_portfolio(portfolio_id, owner_id)
        portfolio = get_portfolio(portfolio_id) or {}
    return portfolio_id, portfolio


def _place_paper_order(owner_id: str, symbol: str, side: str, qty: int) -> dict[str, Any]:
    from app.models import OrderSide, OrderType
    from app.services.fill_simulator import FillSimulator
    from app.services.paper_portfolio import PaperPortfolioService

    portfolio_id, _ = _paper_state(owner_id)
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


# --- Cycle -----------------------------------------------------------------


def log_decision(
    owner_id: str,
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
               (id, owner_id, ts, symbol, action, confidence, reason, price, qty, route, ok, detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid4()),
                owner_id,
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


async def evaluate_symbol(owner_id: str, symbol: str, config: dict[str, Any]) -> dict[str, Any]:
    """Decide what to do with one symbol (no side effects)."""
    from app.services.market_data import fetch_ohlcv

    result = await fetch_ohlcv(symbol, 120)
    closes = [float(c) for c in result.dataframe["Close"].tolist()]
    price = closes[-1] if closes else None

    signal, raw_conf, signal_reason = score_symbol(closes, config["strategy"])
    confidence, memory_note = apply_memory(owner_id, symbol, raw_conf, config)

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": confidence,
        "price": price,
        "reason": f"{signal_reason} | {memory_note}",
    }


async def run_cycle(owner_id: str) -> dict[str, Any]:
    """One full evaluation + execution pass over the owner's paper simulator."""
    config = get_config(owner_id)
    symbols: list[str] = config["symbols"]
    results: list[dict[str, Any]] = []

    portfolio_id, portfolio = _paper_state(owner_id)
    positions: dict[str, float] = {
        str(p.get("instrument_id", "")).upper(): float(p.get("quantity", 0))
        for p in portfolio.get("positions", [])
    }

    cash = float(portfolio.get("cash") or 0.0)
    threshold = float(config["confidence_threshold"])
    max_notional = float(config["max_position_notional"])

    for symbol in symbols:
        try:
            decision = await evaluate_symbol(owner_id, symbol, config)
        except Exception as exc:
            log_decision(
                owner_id, symbol, "error", 0.0, "evaluation failed", ok=False, detail=str(exc)
            )
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
                        _place_paper_order(owner_id, symbol, "sell", qty)
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
                    _place_paper_order(owner_id, symbol, "buy", qty)
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
                owner_id,
                symbol,
                action,
                confidence,
                decision["reason"],
                price=price,
                qty=None,
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
            log_decision(
                owner_id,
                symbol,
                action,
                confidence,
                decision["reason"],
                price=price,
                ok=False,
                detail=str(exc),
            )
            results.append({"symbol": symbol, "action": "error", "detail": str(exc)})

    return {"route": "paper", "decisions": results, "ts": _now()}


def recent_log(owner_id: str, limit: int = 50) -> list[dict[str, Any]]:
    _ensure_tables()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_trading_log WHERE owner_id = ? ORDER BY ts DESC LIMIT ?",
            (owner_id, max(1, min(int(limit), 500))),
        ).fetchall()
    return [dict(row) for row in rows]


# --- Background loop -------------------------------------------------------

_loop_tasks: dict[str, asyncio.Task] = {}


def is_running(owner_id: str) -> bool:
    task = _loop_tasks.get(owner_id)
    return task is not None and not task.done()


async def _cycle_loop(owner_id: str) -> None:
    while True:
        config = get_config(owner_id)
        if not config.get("enabled"):
            break
        try:
            await run_cycle(owner_id)
        except Exception as exc:  # keep the loop alive no matter what
            log_decision(owner_id, "", "error", 0.0, "cycle failed", ok=False, detail=str(exc))
        await asyncio.sleep(max(15, int(config.get("cycle_seconds", 60))))


def start(owner_id: str) -> dict[str, Any]:
    config = get_config(owner_id)
    config["enabled"] = True
    save_config(owner_id, config)
    if not is_running(owner_id):
        _loop_tasks[owner_id] = asyncio.get_running_loop().create_task(
            _cycle_loop(owner_id), name=f"ai-trading-{owner_id}"
        )
    return get_config(owner_id)


def stop(owner_id: str) -> dict[str, Any]:
    config = get_config(owner_id)
    config["enabled"] = False
    save_config(owner_id, config)
    task = _loop_tasks.pop(owner_id, None)
    if task is not None and not task.done():
        task.cancel()
    return get_config(owner_id)


def shutdown() -> None:
    """Cancel every owner's loop on process exit without clearing config."""
    for task in list(_loop_tasks.values()):
        if not task.done():
            task.cancel()
    _loop_tasks.clear()


def autostart() -> list[str]:
    """Resume each owner whose agent was left enabled."""
    started: list[str] = []
    for owner_id in enabled_owners():
        try:
            start(owner_id)
            started.append(owner_id)
        except Exception:
            continue
    return started


def status(owner_id: str) -> dict[str, Any]:
    config = get_config(owner_id)
    return {
        "running": is_running(owner_id),
        "config": config,
        "last_log": recent_log(owner_id, 5),
        "journal_memory": {s: journal_memory(owner_id, s) for s in config["symbols"][:8]},
        "backtest_edge": backtest_edge(owner_id),
    }
