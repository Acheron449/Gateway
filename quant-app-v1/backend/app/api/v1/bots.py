"""Bot runner HTTP surface (SRS FR-R2).

Every route is owner-scoped: a run id belonging to someone else is a 404, the
same answer as an id that does not exist.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.services import bot_runner

router = APIRouter(prefix="/bots", tags=["bots"])


class BotRunRequest(BaseModel):
    strategy: dict[str, Any] | None = None
    strategy_id: str | None = None
    strategy_version: int | None = None
    instrument: str | None = None
    timeframe: str | None = None
    portfolio_id: str | None = None
    interval_seconds: int = Field(default=60, ge=60)
    max_iterations: int = Field(default=10, ge=1, le=bot_runner.MAX_ITERATIONS_CAP)
    max_duration_minutes: int = Field(default=60, ge=1, le=bot_runner.MAX_DURATION_MINUTES_CAP)
    source: str = "delayed"
    live: bool = False


@router.post("/runs")
async def start_bot_run(payload: BotRunRequest, user: CurrentUser) -> dict:
    try:
        run = bot_runner.create_run(user.id, payload.model_dump())
    except bot_runner.BotRunError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    bot_runner.start_loop(run["id"])
    return {"run": run}


@router.get("/runs")
async def list_bot_runs(user: CurrentUser) -> dict:
    return {"runs": bot_runner.list_runs(user.id)}


@router.get("/runs/{run_id}")
async def get_bot_run(run_id: str, user: CurrentUser) -> dict:
    run = bot_runner.get_run(run_id)
    if run is None or run["owner_id"] != user.id:
        raise HTTPException(status_code=404, detail=f"bot run '{run_id}' not found")
    return {"run": run}


@router.post("/runs/{run_id}/stop")
async def stop_bot_run(run_id: str, user: CurrentUser) -> dict:
    try:
        run = bot_runner.stop_run(user.id, run_id)
    except bot_runner.BotRunError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"run": run}


@router.get("/runs/{run_id}/log")
async def bot_run_log(run_id: str, user: CurrentUser) -> dict:
    try:
        rows = bot_runner.decisions(user.id, run_id)
    except bot_runner.BotRunError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"run_id": run_id, "decisions": rows}
