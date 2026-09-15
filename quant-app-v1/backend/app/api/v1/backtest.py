from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException

from app.engine.backtester import BacktestEngine
from app.quant.risk_manager import RiskConfig
from app.services import database
from app.services.broker_service import BrokerService

router = APIRouter(prefix="/backtest", tags=["backtest"])


async def _run_backtest_job_payload(job_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    bars = payload.get("bars")
    if not bars or not isinstance(bars, list):
        raise ValueError("bars must be provided as a non-empty list")

    initial_capital = float(payload.get("initial_capital", 100000.0))
    provider_pref = payload.get("provider_preference")

    try:
        df = pd.DataFrame(bars)
        if 'Timestamp' in df.columns:
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    except Exception as exc:
        raise ValueError(f"Invalid bars payload: {exc}") from exc

    broker = BrokerService(provider_preference=provider_pref)
    engine = BacktestEngine(initial_capital=initial_capital, risk_config=RiskConfig())

    start_ts = datetime.utcnow().isoformat()
    results = await engine.run_simulation(df, broker=broker)
    end_ts = datetime.utcnow().isoformat()

    backtest_id = None
    try:
        backtest_id = database.insert_backtest(start_ts, end_ts, initial_capital, engine.current_capital, len(results))
        for t in results:
            database.insert_trade(
                backtest_id,
                t.signal_time.isoformat() if hasattr(t.signal_time, 'isoformat') else str(t.signal_time),
                getattr(t, 'symbol', payload.get('symbol', 'TICK')),
                t.signal_direction,
                float(t.confidence),
                float(t.entry_price),
                float(t.exit_price) if t.exit_price is not None else None,
                float(t.pnl_pct),
                t.outcome,
            )
    except Exception as exc:
        print(f"Backtest persistence failed: {exc}")

    analysis = engine.analyze_results(results)
    payload_out = {"backtest_id": backtest_id, "analysis": analysis}
    if job_id:
        database.update_backtest_job(job_id, status='completed', finished_at=datetime.utcnow().isoformat(), backtest_id=backtest_id, result=payload_out)
    return payload_out


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
    Run a backtest from provided historical bars.
    Payload format:
    {
      "bars": [ {"Timestamp": "2026-09-15T00:00:00", "Price": 100.0, "Sentiment_Score": 0.5, "Pattern_Features": [...] , "Symbol": "AAPL" }, ... ],
      "initial_capital": 100000,
      "provider_preference": "finnhub",  # optional
      "async_run": true  # optional: queue job and return job_id
    }
    """
    if payload.get("async_run") or payload.get("background"):
        job_id = database.create_backtest_job(payload=payload)
        asyncio.create_task(_backtest_worker(job_id, payload), name=f"backtest-job-{job_id}")
        return {"job_id": job_id, "status": "queued", "message": "Backtest queued and running in the background."}

    return await _run_backtest_job_payload(job_id=None, payload=payload)


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
