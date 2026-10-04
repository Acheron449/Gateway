"""Agentic Trading Lab API — agents, backtest jobs, and performance stats.

Mirrors the Open-Finance-Lab AgenticTrading workflow in miniature:
prototype an agent (model + prompt), backtest it against historical bars,
inspect every decision, and compare runs against baselines with
plain-language statistics.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.services import job_store
from app.services import lab_backtest as lab


router = APIRouter(prefix="/agentic-lab", tags=["agentic-lab"])

PROMPT_PRESETS = [
    {
        "id": "trend",
        "label": "Trend follower",
        "prompt": (
            "You are a systematic trend-following trader. Go long while the market shows "
            "higher highs and the moving averages point up; go flat when the trend fades. "
            "Never short. Only trade when the trend is clear. "
            "Answer with JSON only: {\"action\": \"long|flat\", \"reason\": \"one sentence\"}."
        ),
    },
    {
        "id": "mean-reversion",
        "label": "Mean reversion",
        "prompt": (
            "You are a mean-reversion trader. Buy when the price is stretched below its recent "
            "average (oversold RSI), exit when it normalises, and stay flat otherwise. "
            "Answer with JSON only: {\"action\": \"long|flat|short\", \"reason\": \"one sentence\"}."
        ),
    },
    {
        "id": "discretionary",
        "label": "Discretionary analyst",
        "prompt": lab.DEFAULT_PROMPT,
    },
]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AgentRequest(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1, max_length=80)
    kind: str = Field(default="llm")
    baseline: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None
    symbol: Optional[str] = None
    tf: Optional[str] = "1d"


class BacktestRequest(BaseModel):
    kind: str = Field(default="baseline", description="llm | baseline")
    baseline: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None
    agent_id: Optional[str] = None
    symbol: str = Field(min_length=1, max_length=20)
    tf: str = Field(default="1d")
    bars: int = Field(default=260, ge=40, le=1000)
    capital: float = Field(default=10_000.0, ge=100, le=10_000_000)
    max_llm_calls: int = Field(default=16, ge=1, le=40)
    fee_bps: float = Field(default=5.0, ge=0, le=100)
    slippage_bps: float = Field(default=5.0, ge=0, le=100)


# ---------------------------------------------------------------------------
# Catalogue & agents
# ---------------------------------------------------------------------------

@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    """Baselines, prompt presets, and stats legend for the lab UI."""
    return {
        "baselines": [{"id": key, **value} for key, value in lab.BASELINES.items()],
        "prompt_presets": PROMPT_PRESETS,
        "default_prompt": lab.DEFAULT_PROMPT,
        "stats_legend": [
            {"label": "Total return", "hint": "Profit/loss on the starting equity"},
            {"label": "Sharpe", "hint": "Risk-adjusted return — above 1 is good"},
            {"label": "Max drop", "hint": "Worst peak-to-trough decline along the way"},
            {"label": "Win rate", "hint": "Share of trades that ended green"},
        ],
        "timeframes": [
            {"id": "1d", "label": "Daily"},
            {"id": "1h", "label": "Hourly"},
            {"id": "1wk", "label": "Weekly"},
        ],
    }


@router.get("/agents")
async def get_agents() -> dict[str, Any]:
    return {"agents": lab.list_agents()}


@router.post("/agents")
async def upsert_agent(request: AgentRequest, user: CurrentUser) -> dict[str, Any]:
    if request.kind == "baseline" and (request.baseline not in lab.BASELINES):
        raise HTTPException(status_code=400, detail=f"Unknown baseline '{request.baseline}'")
    if request.kind == "llm" and not request.provider:
        raise HTTPException(status_code=400, detail="Model agents need a provider")
    agent = lab.save_agent(request.model_dump())
    return {"agent": agent}


@router.delete("/agents/{agent_id}")
async def remove_agent(agent_id: str, user: CurrentUser) -> dict[str, Any]:
    if not lab.delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Backtest jobs
# ---------------------------------------------------------------------------

@router.post("/backtest")
async def start_backtest(request: BacktestRequest, user: CurrentUser) -> dict[str, Any]:
    """Start a lab backtest; poll /agentic-lab/jobs/{id} for progress/result."""
    spec = {
        "kind": request.kind,
        "baseline": request.baseline,
        "provider": request.provider,
        "model": request.model,
        "prompt": request.prompt,
    }
    if request.agent_id:
        agent = next((a for a in lab.list_agents() if a.get("id") == request.agent_id), None)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        spec = {
            "kind": agent.get("kind") or "llm",
            "baseline": agent.get("baseline"),
            "provider": agent.get("provider"),
            "model": agent.get("model"),
            "prompt": agent.get("prompt"),
        }
        if spec["kind"] == "baseline" and not request.baseline:
            spec["baseline"] = agent.get("baseline") or "buy_hold"

    if spec["kind"] == "llm" and not (spec.get("provider") and spec.get("model")):
        raise HTTPException(status_code=400, detail="A model strategy needs a provider and a model")
    if spec["kind"] == "baseline" and spec.get("baseline") not in lab.BASELINES:
        raise HTTPException(status_code=400, detail=f"Unknown baseline '{spec.get('baseline')}'")

    meta = {
        "spec": spec,
        "symbol": request.symbol.strip().upper(),
        "tf": request.tf,
        "bars": request.bars,
        "capital": request.capital,
        "max_llm_calls": request.max_llm_calls,
        "fee_bps": request.fee_bps,
        "slippage_bps": request.slippage_bps,
        "agent_id": request.agent_id,
    }
    job_id = job_store.create("lab-backtest", meta)
    job_store.update(job_id, message="Fetching market history…", progress=0.1)

    async def worker(active_id: str) -> None:
        async def progress(done: int, total: int, message: str) -> None:
            fraction = 0.2 + 0.7 * (done / max(1, total))
            job_store.update(active_id, progress=round(fraction, 3), message=message)

        run = await lab.run_backtest(
            spec,
            symbol=meta["symbol"],
            tf=meta["tf"],
            bars_limit=meta["bars"],
            capital=meta["capital"],
            max_llm_calls=meta["max_llm_calls"],
            fee_bps=meta["fee_bps"],
            slippage_bps=meta["slippage_bps"],
            agent_id=meta["agent_id"],
            on_progress=progress,
        )
        job_store.update(active_id, result=run, progress=1.0, message="Run complete")

    job_store.run_async_worker(job_id, worker)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = job_store.get(job_id)
    if job is None or job["kind"] != "lab-backtest":
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Runs & stats
# ---------------------------------------------------------------------------

@router.get("/runs")
async def get_runs(limit: int = 20) -> dict[str, Any]:
    """Stored runs with full metrics plus plain-language header stats."""
    runs = lab.list_runs(limit=min(max(limit, 1), lab.MAX_RUNS))
    return {"runs": runs, "summary": lab.runs_summary(runs)}


@router.delete("/runs/{run_id}")
async def remove_run(run_id: str, user: CurrentUser) -> dict[str, Any]:
    if not lab.delete_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"deleted": True}
