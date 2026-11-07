"""Bot runner (SRS FR-R1..R6).

A bot binds one strategy version to one instrument, timeframe and demo
portfolio, then ticks on a schedule (minimum 60 s). It holds **no privileged
write access**: every order goes through
:func:`app.services.order_admission.admit_order`, so the kill switch, risk
limits and cash reservation apply to a bot exactly as they do to a human
request.

Bots read delayed bars only — there is no live feed parameter, and asking for
one is an error rather than a silent downgrade.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger

from app.models import OrderSide, OrderType
from app.services import database
from app.services.backtest_engine import latest_signal
from app.services.bars import BarsUnavailable, fetch_bars
from app.services.database import get_portfolio
from app.services.order_admission import AdmissionError, admit_order

MIN_INTERVAL_SECONDS = 60
MAX_CONCURRENT_RUNS = 2
MAX_ITERATIONS_CAP = 500
MAX_DURATION_MINUTES_CAP = 240
ALLOWED_SOURCES = {"delayed", "historical"}


class BotRunError(Exception):
    """A request the bot runner refuses, with the HTTP status to surface."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_spec(payload: dict[str, Any]) -> tuple[dict, str, int]:
    spec = payload.get("strategy")
    sid = str(payload.get("strategy_id") or "")
    version = int(payload.get("strategy_version") or 0)
    if isinstance(spec, dict):
        return spec, sid, version
    if not sid:
        raise BotRunError("supply a strategy spec or a strategy_id")
    database.init_db()
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM strategy_versions WHERE strategy_id = ? AND version = ?",
            (sid, version),
        ).fetchone()
        if row is None and version == 0:
            row = conn.execute(
                "SELECT * FROM strategy_versions WHERE strategy_id = ? ORDER BY version DESC LIMIT 1",
                (sid,),
            ).fetchone()
    if row is None:
        raise BotRunError(f"strategy version {version or 'latest'} not found", 404)
    import json

    return json.loads(row["spec"]), sid, int(row["version"])


def create_run(owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and persist a bot run, then return it."""
    interval = int(payload.get("interval_seconds") or MIN_INTERVAL_SECONDS)
    if interval < MIN_INTERVAL_SECONDS:
        raise BotRunError(f"interval_seconds must be at least {MIN_INTERVAL_SECONDS}")

    source = str(payload.get("source") or "delayed").lower()
    if payload.get("live") or source not in ALLOWED_SOURCES:
        raise BotRunError("bots run on delayed or historical data only; live feeds are not supported")

    max_iterations = int(payload.get("max_iterations") or 10)
    if not 1 <= max_iterations <= MAX_ITERATIONS_CAP:
        raise BotRunError(f"max_iterations must be between 1 and {MAX_ITERATIONS_CAP}")
    max_duration = int(payload.get("max_duration_minutes") or 60)
    if not 1 <= max_duration <= MAX_DURATION_MINUTES_CAP:
        raise BotRunError(f"max_duration_minutes must be between 1 and {MAX_DURATION_MINUTES_CAP}")

    if database.count_running_bot_runs(owner_id) >= MAX_CONCURRENT_RUNS:
        raise BotRunError(
            f"at most {MAX_CONCURRENT_RUNS} bot runs may be active per user", 429
        )

    spec, strategy_id, version = _load_spec(payload)
    universe = spec.get("asset_universe") or []
    instrument = str(payload.get("instrument") or (universe[0] if universe else "")).upper()
    if not instrument:
        raise BotRunError("instrument is required")
    timeframe = str(payload.get("timeframe") or spec.get("timeframe") or "1h")
    portfolio_id = str(payload.get("portfolio_id") or "paper_default")
    if get_portfolio(portfolio_id) is None:
        database.create_portfolio(portfolio_id, owner_id)

    run_id = f"bot_{uuid.uuid4().hex[:12]}"
    row = {
        "id": run_id,
        "owner_id": owner_id,
        "portfolio_id": portfolio_id,
        "strategy_id": strategy_id,
        "strategy_version": version,
        "spec": spec,
        "instrument": instrument,
        "timeframe": timeframe,
        "interval_seconds": interval,
        "max_iterations": max_iterations,
        "max_duration_minutes": max_duration,
        "status": "running",
        "source": source,
        "created_at": _now(),
        "started_at": _now(),
    }
    return database.create_bot_run(row)


def get_run(run_id: str) -> dict[str, Any] | None:
    return database.get_bot_run(run_id)


def list_runs(owner_id: str) -> list[dict[str, Any]]:
    return database.list_bot_runs(owner_id)


def stop_run(owner_id: str, run_id: str, reason: str = "stopped_by_user") -> dict[str, Any]:
    run = database.get_bot_run(run_id)
    if run is None or run["owner_id"] != owner_id:
        raise BotRunError(f"bot run '{run_id}' not found", 404)
    if run["status"] == "running":
        database.update_bot_run(run_id, status="stopped", stopped_at=_now(), stop_reason=reason)
    return database.get_bot_run(run_id) or run


def decisions(owner_id: str, run_id: str) -> list[dict[str, Any]]:
    run = database.get_bot_run(run_id)
    if run is None or run["owner_id"] != owner_id:
        raise BotRunError(f"bot run '{run_id}' not found", 404)
    return database.list_bot_decisions(run_id)


def _held_qty(portfolio_id: str, instrument: str) -> float:
    portfolio = get_portfolio(portfolio_id) or {}
    for pos in portfolio.get("positions", []):
        if str(pos.get("instrument_id", "")).upper() == instrument.upper():
            return float(pos.get("quantity") or 0.0)
    return 0.0


def run_once(run_id: str, bars: list[dict] | None = None) -> dict[str, Any] | None:
    """One decision cycle: read delayed bars, decide, admit, log.

    Returns the decision row (or None when the run is no longer running).
    """
    run = database.get_bot_run(run_id)
    if run is None or run["status"] != "running":
        return None
    iterations = int(run.get("iterations") or 0)
    if iterations >= int(run.get("max_iterations") or 1):
        database.update_bot_run(
            run_id, status="stopped", stopped_at=_now(), stop_reason="max_iterations"
        )
        return None

    instrument = str(run["instrument"]).upper()
    spec = run["spec"] if isinstance(run["spec"], dict) else {}
    try:
        bars = bars if bars is not None else fetch_bars(instrument, run["timeframe"], limit=300)
    except BarsUnavailable as exc:
        _record(run, iterations, instrument, {"error": str(exc)}, "unavailable", "skipped", str(exc))
        return database.list_bot_decisions(run_id)[-1] if database.list_bot_decisions(run_id) else None

    signal = latest_signal(spec, bars)
    price = float(bars[-1]["close"]) if bars else None
    held = _held_qty(run["portfolio_id"], instrument)
    action = "hold"
    verdict = "passed"
    detail = None

    position_pct = float(signal.get("params", {}).get("position_pct", 0.1) or 0.1)
    portfolio = get_portfolio(run["portfolio_id"]) or {}
    equity = float(portfolio.get("equity") or portfolio.get("cash") or 0.0)

    try:
        if signal.get("action") == "enter" and held <= 0 and price:
            qty = math.floor((equity * position_pct) / price)
            if qty > 0:
                decision = admit_order(
                    portfolio_id=run["portfolio_id"],
                    instrument=instrument,
                    side=OrderSide.BUY if signal["signal"] == "long" else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    qty=qty,
                    price=price,
                    source="bot",
                )
                action = "buy" if decision.accepted else "blocked"
                verdict = "passed" if decision.accepted else (decision.reason or decision.status)
                detail = decision.reason
            else:
                action = "skipped"
                detail = "position size rounds to zero shares"
        elif signal.get("action") == "exit" and held > 0:
            decision = admit_order(
                portfolio_id=run["portfolio_id"],
                instrument=instrument,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                qty=held,
                price=price,
                source="bot",
            )
            action = "sell" if decision.accepted else "blocked"
            verdict = "passed" if decision.accepted else (decision.reason or decision.status)
            detail = decision.reason
    except AdmissionError as exc:
        action, verdict, detail = "error", str(exc), str(exc)

    row = _record(run, iterations, instrument, signal.get("inputs", {}), signal.get("signal", "none"), verdict, action, detail)
    next_iterations = iterations + 1
    database.update_bot_run(run_id, iterations=next_iterations, last_tick_at=_now())
    if next_iterations >= int(run.get("max_iterations") or 1):
        database.update_bot_run(run_id, status="stopped", stopped_at=_now(), stop_reason="max_iterations")
    return row


def _record(
    run: dict,
    seq: int,
    instrument: str,
    inputs: dict,
    signal: str,
    verdict: str,
    action: str,
    detail: str | None,
) -> dict:
    database.append_bot_decision(
        decision_id=f"dec_{uuid.uuid4().hex[:12]}",
        run_id=run["id"],
        seq=seq,
        at=_now(),
        symbol=instrument,
        inputs=inputs,
        signal=signal,
        risk_verdict=verdict,
        action=action,
        detail=detail,
    )
    rows = database.list_bot_decisions(run["id"])
    return rows[-1] if rows else {}


async def _loop(run_id: str) -> None:
    """Tick until stopped, out of iterations, or past the duration bound."""
    while True:
        run = database.get_bot_run(run_id)
        if run is None or run["status"] != "running":
            return
        started = run.get("started_at") or run.get("created_at")
        try:
            started_at = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        except ValueError:
            started_at = datetime.now(timezone.utc)
        deadline = started_at + timedelta(minutes=int(run.get("max_duration_minutes") or 60))
        if datetime.now(timezone.utc) >= deadline:
            database.update_bot_run(
                run_id, status="stopped", stopped_at=_now(), stop_reason="max_duration"
            )
            return

        try:
            await asyncio.to_thread(run_once, run_id)
        except Exception as exc:  # a bad tick must not kill the runner silently
            logger.exception("Bot run {} tick failed: {}", run_id, exc)
            database.update_bot_run(
                run_id, status="error", stopped_at=_now(), stop_reason=f"error: {exc}"
            )
            return

        interval = int(run.get("interval_seconds") or MIN_INTERVAL_SECONDS)
        slept = 0.0
        while slept < interval:
            await asyncio.sleep(min(2.0, interval - slept))
            slept += 2.0
            current = database.get_bot_run(run_id)
            if current is None or current["status"] != "running":
                return


def start_loop(run_id: str) -> None:
    """Schedule the loop on the running event loop (no-op outside one)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    asyncio.create_task(_loop(run_id), name=f"bot-{run_id}")
