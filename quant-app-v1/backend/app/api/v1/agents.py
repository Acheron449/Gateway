"""TradingAgents API — availability, job creation, and job progress."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.services import job_store
from app.services import trading_agents_service as ta_svc


router = APIRouter(prefix="/agents", tags=["agents"])


class TradingAgentsRunRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    date: Optional[str] = Field(default=None, description="YYYY-MM-DD analysis date (default: today)")
    analysts: list[str] = Field(default_factory=lambda: ["market", "news", "fundamentals"])
    provider: str
    model: Optional[str] = None
    depth: int = Field(default=1, ge=1, le=3)
    language: str = Field(default="English", max_length=32)


@router.get("/trading-agents")
async def get_trading_agents_status() -> dict[str, Any]:
    """Availability + selectable providers/analysts for the TradingAgents panel."""
    availability = ta_svc.tradingagents_available()
    return {
        **availability,
        "analysts": ta_svc.ANALYSTS,
        "depths": ta_svc.RESEARCH_DEPTHS,
        "providers": ta_svc.supported_providers(),
        "running_jobs": len([j for j in job_store.list_jobs("trading-agents", limit=10) if j["status"] == "running"]),
    }


@router.post("/trading-agents/run")
async def run_trading_agents(request: TradingAgentsRunRequest, user: CurrentUser) -> dict[str, Any]:
    """Start a multi-agent analysis; poll /agents/jobs/{id} for progress/result."""
    availability = ta_svc.tradingagents_available()
    if not availability["available"]:
        raise HTTPException(status_code=503, detail=availability["message"])

    analysts = [a for a in request.analysts if a in {row["id"] for row in ta_svc.ANALYSTS}]
    if not analysts:
        raise HTTPException(status_code=400, detail="Pick at least one analyst")
    if not request.ticker.strip():
        raise HTTPException(status_code=400, detail="A ticker is required")

    try:
        job_id = ta_svc.start_trading_agents_job(
            ticker=request.ticker.strip(),
            analysis_date=request.date,
            analysts=analysts,
            provider_id=request.provider,
            model=request.model,
            depth=request.depth,
            language=request.language.strip() or "English",
        )
    except ta_svc.llm_svc.LlmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_agent_job(job_id: str) -> dict[str, Any]:
    job = job_store.get(job_id)
    if job is None or job["kind"] != "trading-agents":
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs")
async def list_agent_jobs(limit: int = 10) -> dict[str, Any]:
    return {"jobs": job_store.list_jobs("trading-agents", limit=min(max(limit, 1), 50))}
