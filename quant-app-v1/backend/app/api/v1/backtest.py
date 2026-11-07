"""Backtest runs, receipts and reproducibility (SRS FR-B1..B8, FR-P1..P4).

``POST /backtest/run`` either starts a new run from a typed strategy spec, or
replays an existing receipt. A replay re-derives the bar set from the receipt's
symbol/window and refuses to proceed when the data hash no longer matches —
returning different numbers for the same receipt would make the receipt
meaningless.

Every run is owner-scoped and retained to 50 per owner (oldest pruned).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import CurrentUser, User
from app.services import bars as bars_service
from app.services import database
from app.services.backtest_engine import (
    ENGINE_VERSION,
    data_hash as compute_data_hash,
    normalize_bars,
    run_backtest as run_engine,
)

router = APIRouter(prefix="/backtest", tags=["backtest"])

# FR-D6: a backtest may not exceed this many bars for a single symbol.
BACKTEST_MAX_BARS_PER_SYMBOL = 5_000


class CostModel(BaseModel):
    commission_per_trade: float = Field(default=1.0, ge=0)
    half_spread_bps: float = Field(default=2.0, ge=0)
    slippage_bps: float = Field(default=2.0, ge=0)
    latency_bars: int = Field(default=0, ge=0, le=10)


class BacktestRunRequest(BaseModel):
    """Either a receipt to replay, or a spec plus instrument to run."""

    receipt: dict[str, Any] | None = None
    strategy: dict[str, Any] | None = None
    strategy_id: str | None = None
    strategy_version: int | None = None
    symbol: str | None = None
    timeframe: str | None = None
    initial_capital: float = Field(default=100_000.0, gt=0)
    costs: CostModel | None = None
    seed: int = 42
    oos_ratio: float = Field(default=0.3, ge=0, le=0.9)
    bars: list[dict[str, Any]] | None = None
    bar_limit: int = Field(default=1000, ge=1, le=BACKTEST_MAX_BARS_PER_SYMBOL)


def _validate_bar_cap(bars: list[dict[str, Any]]) -> None:
    """FR-D6: refuse more than 5,000 bars for any one symbol."""
    counts: dict[str, int] = {}
    for bar in bars:
        if not isinstance(bar, dict):
            raise ValueError("bars must contain objects")
        symbol = str(bar.get("symbol", "")).strip().upper()
        counts[symbol] = counts.get(symbol, 0) + 1
    over_limit = sorted(s for s, count in counts.items() if count > BACKTEST_MAX_BARS_PER_SYMBOL)
    if over_limit:
        raise ValueError(
            f"bars per symbol must be at most {BACKTEST_MAX_BARS_PER_SYMBOL}; "
            f"over the limit: {', '.join(over_limit) or '(unspecified symbol)'}"
        )


def _load_spec_from_strategy(strategy_id: str, version: int | None) -> tuple[dict, str, int]:
    database.init_db()
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        target = version or int(row["current_version"])
        version_row = conn.execute(
            "SELECT * FROM strategy_versions WHERE strategy_id = ? AND version = ?",
            (strategy_id, target),
        ).fetchone()
    if version_row is None:
        raise HTTPException(status_code=404, detail=f"Strategy version {target} not found")
    import json

    return json.loads(version_row["spec"]), strategy_id, target


def _resolve_bars(payload: BacktestRunRequest, receipt: dict | None) -> list[dict]:
    """Explicit bars win (tests and offline replay); otherwise fetch."""
    if payload.bars:
        return payload.bars
    symbol = (receipt or {}).get("symbol") or payload.symbol
    timeframe = (receipt or {}).get("timeframe") or payload.timeframe or "1h"
    limit = int((receipt or {}).get("bars") or payload.bar_limit)
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required when bars are not supplied")
    try:
        return bars_service.fetch_bars(symbol, timeframe, limit=min(limit, BACKTEST_MAX_BARS_PER_SYMBOL))
    except bars_service.BarsUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "source_unavailable", "message": str(exc), "provider": "Yahoo Finance"},
        ) from exc


def _execute(
    *,
    owner_id: str,
    spec: dict,
    bars: list[dict],
    symbol: str,
    timeframe: str,
    initial_capital: float,
    costs: dict,
    seed: int,
    oos_ratio: float,
    expected_hash: str | None,
) -> dict:
    # Normalise once, here, so the hash and the engine see the same rows.
    # Otherwise a caller's int volume and the engine's float volume would hash
    # differently and every replay would look like tampering.
    try:
        _validate_bar_cap(bars)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "bar_limit",
                "message": str(exc),
                "requested": len(bars),
                "max_bars": BACKTEST_MAX_BARS_PER_SYMBOL,
            },
        ) from exc
    bars = normalize_bars(bars)

    if expected_hash is not None:
        actual = compute_data_hash(symbol, timeframe, bars)
        if actual != expected_hash:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "data_changed",
                    "message": "The bars no longer match the receipt; the run cannot be reproduced",
                    "expected_data_hash": expected_hash,
                    "actual_data_hash": actual,
                },
            )

    try:
        result = run_engine(
            spec=spec,
            bars=bars,
            symbol=symbol,
            timeframe=timeframe,
            initial_capital=initial_capital,
            costs=costs,
            seed=seed,
            oos_ratio=oos_ratio,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"bt_{stamp}_{result['data_hash'][:8]}_{uuid.uuid4().hex[:6]}"
    database.save_backtest_receipt(
        run_id=run_id,
        owner_id=owner_id,
        status="completed",
        symbol=symbol,
        timeframe=timeframe,
        data_hash=result["data_hash"],
        receipt=result["receipt"],
        result=result,
        metrics=result["metrics"],
    )
    return {"run_id": run_id, "status": "completed", **result}


@router.post("/run")
async def run_backtest(payload: BacktestRunRequest, user: CurrentUser) -> dict:
    """Run a backtest, or reproduce one from its stored receipt."""
    if payload.receipt:
        receipt = dict(payload.receipt)
        spec = receipt.get("spec")
        if not isinstance(spec, dict):
            raise HTTPException(
                status_code=400,
                detail="receipt is missing its strategy spec and cannot be replayed",
            )
        symbol = str(receipt.get("symbol") or "").upper()
        timeframe = str(receipt.get("timeframe") or "1h")
        if not symbol:
            raise HTTPException(status_code=400, detail="receipt is missing its symbol")
        bars = _resolve_bars(payload, receipt)
        costs = payload.costs.model_dump() if payload.costs else dict(receipt.get("costs") or {})
        return _execute(
            owner_id=user.id,
            spec=spec,
            bars=bars,
            symbol=symbol,
            timeframe=timeframe,
            initial_capital=float(receipt.get("initial_capital") or payload.initial_capital),
            costs=costs,
            seed=int(receipt.get("seed", payload.seed)),
            oos_ratio=float(receipt.get("oos_ratio", payload.oos_ratio)),
            expected_hash=str(receipt.get("data_hash") or "") or None,
        )

    spec = payload.strategy
    if spec is None and payload.strategy_id:
        spec, _sid, _ver = _load_spec_from_strategy(payload.strategy_id, payload.strategy_version)
    if not isinstance(spec, dict):
        raise HTTPException(
            status_code=400,
            detail="supply a typed strategy spec, a strategy_id, or a receipt to replay",
        )

    symbol = (payload.symbol or (spec.get("asset_universe") or [""])[0] or "").upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    timeframe = payload.timeframe or str(spec.get("timeframe") or "1h")
    bars = _resolve_bars(payload, None)
    costs = payload.costs.model_dump() if payload.costs else {}

    return _execute(
        owner_id=user.id,
        spec=spec,
        bars=bars,
        symbol=symbol,
        timeframe=timeframe,
        initial_capital=payload.initial_capital,
        costs=costs,
        seed=payload.seed,
        oos_ratio=payload.oos_ratio,
        expected_hash=None,
    )


@router.get("/runs")
async def list_runs(user: CurrentUser, limit: int = Query(50, ge=1, le=50)) -> dict:
    runs = database.list_backtest_receipts(user.id, limit=limit)
    return {
        "runs": [
            {
                "run_id": row["id"],
                "status": row["status"],
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "data_hash": row["data_hash"],
                "created_at": row["created_at"],
                "metrics": row["metrics"],
            }
            for row in runs
        ],
        "retention": database.RECEIPT_RETENTION,
    }


def _own_run(run_id: str, user: User) -> dict:
    row = database.get_backtest_receipt(run_id, user.id)
    if row is None:
        # Cross-owner ids are indistinguishable from missing ones.
        raise HTTPException(status_code=404, detail=f"Backtest run '{run_id}' not found")
    return row


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: CurrentUser) -> dict:
    row = _own_run(run_id, user)
    return {
        "run_id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "receipt": row["receipt"],
        "metrics": row["metrics"],
        "result": row["result"],
    }


def _csv_safe(value: Any) -> str:
    """Neutralise spreadsheet formula injection (FR-P4)."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@router.get("/runs/{run_id}/csv")
async def download_run_csv(run_id: str, user: CurrentUser):
    from fastapi.responses import Response

    row = _own_run(run_id, user)
    receipt = row["receipt"] or {}
    metrics = row["metrics"] or {}
    result = row["result"] or {}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["section", "key", "value"])
    for key, value in receipt.items():
        if isinstance(value, (dict, list)):
            continue
        writer.writerow([_csv_safe("receipt"), _csv_safe(key), _csv_safe(value)])
    for key, value in metrics.items():
        writer.writerow([_csv_safe("metrics"), _csv_safe(key), _csv_safe(value)])
    writer.writerow([])
    writer.writerow(
        ["trade", "side", "qty", "entry_time", "entry_price", "exit_time", "exit_price", "pnl", "commission"]
    )
    for trade in result.get("trades", []):
        writer.writerow(
            [
                _csv_safe("trade"),
                _csv_safe(trade.get("side")),
                _csv_safe(trade.get("qty")),
                _csv_safe(trade.get("entry_time")),
                _csv_safe(trade.get("entry_price")),
                _csv_safe(trade.get("exit_time")),
                _csv_safe(trade.get("exit_price")),
                _csv_safe(trade.get("pnl")),
                _csv_safe(trade.get("commission")),
            ]
        )

    filename = f"backtest-{row['id']}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class CompareRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=2)


@router.post("/compare")
async def compare_runs(payload: CompareRequest, user: CurrentUser) -> dict:
    left = _own_run(payload.run_ids[0], user)
    right = _own_run(payload.run_ids[1], user)
    left_metrics = left["metrics"] or {}
    right_metrics = right["metrics"] or {}
    keys = sorted(set(left_metrics) | set(right_metrics))
    deltas: dict[str, Any] = {}
    for key in keys:
        a, b = left_metrics.get(key), right_metrics.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            deltas[key] = round(b - a, 6)
        else:
            deltas[key] = {"left": a, "right": b}
    return {
        "left": {"run_id": left["id"], "receipt": left["receipt"], "metrics": left_metrics},
        "right": {"run_id": right["id"], "receipt": right["receipt"], "metrics": right_metrics},
        "deltas": deltas,
        "engine_version": ENGINE_VERSION,
    }


# --- Legacy job endpoints -------------------------------------------------
# Kept because older clients poll them; they share the same storage and never
# execute a second, unvalidated backtest path.


@router.get("/status/{job_id}")
@router.get("/jobs/{job_id}")
async def get_backtest_status(job_id: str) -> dict:
    job = database.get_backtest_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Backtest job '{job_id}' not found")
    return job


@router.get("/jobs")
async def list_backtest_jobs() -> dict:
    return {"jobs": database.list_backtest_jobs(limit=50)}

