from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services import database

router = APIRouter(prefix="/backtest", tags=["backtest"])


def _validate_backtest_payload(payload: dict[str, Any]) -> None:
    if payload.get("provider_preference"):
        raise ValueError("provider_preference is not supported; backtests require an approved typed StrategySpec")
    bars = payload.get("bars")
    if not bars or not isinstance(bars, list):
        raise ValueError("bars must be provided as a non-empty list")
    raise ValueError("Backtest execution is unavailable until an approved typed StrategySpec is supplied")


async def _run_backtest_job_payload(job_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    _validate_backtest_payload(payload)
    raise ValueError("Backtest execution is unavailable until an approved typed StrategySpec is supplied")


async def _backtest_worker(job_id: str, payload: dict[str, Any]) -> None:
    database.update_backtest_job(job_id, status='running', started_at=datetime.utcnow().isoformat())
    try:
        await _run_backtest_job_payload(job_id, payload)
    except Exception as exc:
        database.update_backtest_job(job_id, status='failed', finished_at=datetime.utcnow().isoformat(), error=str(exc))
        print(f"Backtest job {job_id} failed: {exc}")


@router.post("/run")
async def run_backtest(payload: dict[str, Any]) -> dict:
    """
    Backtest execution is intentionally unavailable until the legacy payload is
    replaced by an approved typed StrategySpec and the current BacktestConfig API.
    """
    try:
        _validate_backtest_payload(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.get("async_run") or payload.get("background"):
        job_id = database.create_backtest_job(payload=payload)
        asyncio.create_task(_backtest_worker(job_id, payload), name=f"backtest-job-{job_id}")
        return {"job_id": job_id, "status": "queued", "message": "Backtest queued and running in the background."}

    raise HTTPException(status_code=503, detail="Backtest execution is unavailable until an approved typed StrategySpec is supplied")


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
