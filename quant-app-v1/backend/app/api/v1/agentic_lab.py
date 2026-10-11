"""Agentic Trading Lab API — agents, backtest jobs, and performance stats.

Mirrors the Open-Finance-Lab AgenticTrading workflow in miniature:
prototype an agent (model + prompt), backtest it against historical bars,
inspect every decision, and compare runs against baselines with
plain-language statistics.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field, model_validator

from app.auth import CurrentUser
from app.services import job_store
from app.services import lab_backtest as lab
from app.services import llm_providers as llm_svc
from app.services import research_store as research


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


class PairBacktestConfig(BaseModel):
    lookback: int = Field(default=60, ge=30, le=250)
    entry_z: float = Field(default=2.0, gt=0, le=5)
    exit_z: float = Field(default=0.5, ge=0, le=4)
    cointegration_pvalue: float = Field(default=0.05, gt=0, lt=1)
    walk_forward_folds: int = Field(default=4, ge=1, le=10)
    spread_floor_bps: float = Field(default=2.0, ge=0, le=100)
    range_factor: float = Field(default=0.1, ge=0, le=2)
    participation_rate: float = Field(default=0.1, gt=0, le=0.25)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "PairBacktestConfig":
        if self.exit_z >= self.entry_z:
            raise ValueError("exit_z must be less than entry_z")
        return self


class BacktestRequest(BaseModel):
    @model_validator(mode="after")
    def validate_pair_symbols(self) -> "BacktestRequest":
        if self.kind == "pairs" and (not self.symbol_b or self.symbol.strip().upper() == self.symbol_b.strip().upper()):
            raise ValueError("Pairs backtests need two distinct symbols")
        if self.kind == "pairs" and self.pair_config is None:
            raise ValueError("pair_config is required for pairs backtests")
        return self

    kind: str = Field(default="baseline", description="llm | baseline | pairs")
    symbol_b: Optional[str] = Field(default=None, min_length=1, max_length=20)
    pair_config: Optional[PairBacktestConfig] = None
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
    risk: Optional[dict] = Field(
        default=None,
        description="Risk-guard rules: max_position_pct, max_drawdown_pct, allow_short",
    )


class ResearchRequest(BaseModel):
    title: str = Field(default="Untitled research", max_length=120)
    content: str = Field(min_length=1, max_length=200_000)
    source: str = Field(default="typed")
    symbol: Optional[str] = Field(default=None, max_length=20)


class ResearchGenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=400)
    provider: str
    model: str
    symbol: Optional[str] = Field(default=None, max_length=20)


class TradingLogQuery(BaseModel):
    days: int = Field(default=30, ge=1, le=730)
    symbol: Optional[str] = None


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
        "risk_defaults": lab.DEFAULT_RISK_RULES,
        "risk_rules": lab.RISK_RULE_META,
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
    if spec["kind"] not in ("llm", "baseline", "pairs"):
        raise HTTPException(status_code=400, detail="kind must be llm, baseline, or pairs")
    pair_config = None
    if spec["kind"] == "pairs":
        symbol_b = (request.symbol_b or "").strip().upper()
        if not symbol_b or symbol_b == request.symbol.strip().upper():
            raise HTTPException(status_code=422, detail="Pairs backtests need two distinct symbols")
        if request.pair_config is None:
            raise HTTPException(status_code=422, detail="pair_config is required for pairs backtests")
        pair_config = request.pair_config.model_dump()

    meta = {
        "spec": spec,
        "symbol": request.symbol.strip().upper(),
        "symbol_b": (request.symbol_b or "").strip().upper() or None,
        "pair_config": pair_config,
        "tf": request.tf,
        "bars": request.bars,
        "capital": request.capital,
        "max_llm_calls": request.max_llm_calls,
        "fee_bps": request.fee_bps,
        "slippage_bps": request.slippage_bps,
        "agent_id": request.agent_id,
        "risk": lab.normalize_rules(request.risk),
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
            symbol_b=meta.get("symbol_b"),
            pair_config=meta.get("pair_config"),
            tf=meta["tf"],
            bars_limit=meta["bars"],
            capital=meta["capital"],
            max_llm_calls=meta["max_llm_calls"],
            fee_bps=meta["fee_bps"],
            slippage_bps=meta["slippage_bps"],
            agent_id=meta["agent_id"],
            risk=meta.get("risk"),
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


# ---------------------------------------------------------------------------
# Trading log — what the models chose over a user-set duration
# ---------------------------------------------------------------------------

@router.get("/trading-log")
async def get_trading_log(days: int = 30, symbol: Optional[str] = None) -> dict[str, Any]:
    """Every recorded model decision inside the window, newest first."""
    from datetime import datetime, timedelta, timezone

    days = max(1, min(int(days), 730))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    wanted = (symbol or "").strip().upper() or None

    entries: list[dict[str, Any]] = []
    runs_seen = 0
    for run in lab.list_runs(limit=lab.MAX_RUNS):
        if wanted and run.get("symbol") != wanted:
            continue
        decisions = run.get("decisions") or []
        if not decisions:
            continue
        runs_seen += 1
        for decision in decisions:
            stamp = decision.get("time")
            try:
                when = datetime.fromtimestamp(int(stamp), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                continue
            if when < cutoff:
                continue
            entries.append({
                "time": when.isoformat(),
                "run_id": run.get("id"),
                "symbol": run.get("symbol"),
                "strategy": run.get("strategy"),
                "kind": run.get("kind"),
                "provider": run.get("provider"),
                "model": run.get("model"),
                "tf": run.get("tf"),
                "action": decision.get("action"),
                "price": decision.get("price"),
                "reason": decision.get("reason"),
                "risk": decision.get("risk"),
            })
    entries.sort(key=lambda e: e["time"], reverse=True)

    counts = {"long": 0, "flat": 0, "short": 0}
    for entry in entries:
        action = entry.get("action")
        if action in counts:
            counts[action] += 1
    overrides = sum(1 for entry in entries if entry.get("risk"))
    return {
        "window_days": days,
        "symbol": wanted,
        "entries": entries[:200],
        "total": len(entries),
        "runs_covered": runs_seen,
        "counts": counts,
        "risk_overrides": overrides,
    }


# ---------------------------------------------------------------------------
# Research: typed, uploaded, or requested from a model via the harness
# ---------------------------------------------------------------------------

@router.get("/research")
async def get_research() -> dict[str, Any]:
    return {"research": research.list_docs()}


@router.post("/research")
async def save_research(request: ResearchRequest, user: CurrentUser) -> dict[str, Any]:
    try:
        doc = research.save_doc(
            title=request.title,
            content=request.content,
            source=request.source if request.source in ("typed", "uploaded", "model") else "typed",
            symbol=request.symbol,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"research": doc}


@router.post("/research/upload")
async def upload_research(file: "UploadFile", user: CurrentUser) -> dict[str, Any]:
    """Upload a .txt / .md / .csv research file."""
    name = file.filename or "uploaded research.txt"
    if "." in name and name.rsplit(".", 1)[1].lower() not in ("txt", "md", "csv", "log"):
        raise HTTPException(status_code=400, detail="Supported uploads: .txt, .md, .csv, .log")
    raw = await file.read(200_001)
    if len(raw) > 200_000:
        raise HTTPException(status_code=413, detail="Research files are limited to 200 KB")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be UTF-8 text") from exc
    title = name.rsplit(".", 1)[0] if "." in name else name
    try:
        doc = research.save_doc(title=title, content=text, source="uploaded")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"research": doc}


@router.delete("/research/{doc_id}")
async def remove_research(doc_id: str, user: CurrentUser) -> dict[str, Any]:
    if not research.delete_doc(doc_id):
        raise HTTPException(status_code=404, detail="Research not found")
    return {"deleted": True}


@router.post("/research/generate")
async def generate_research(request: ResearchGenerateRequest, user: CurrentUser) -> dict[str, Any]:
    """Ask the chosen harness model for a research draft (not auto-saved)."""
    try:
        llm_svc.resolve_endpoint(request.provider)
        content = await llm_svc.chat_once(
            request.provider,
            request.model,
            research.research_prompt(request.topic, request.symbol),
            max_tokens=1400,
            timeout=120.0,
        )
    except llm_svc.LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "draft": {
            "title": request.topic[:120],
            "content": content,
            "source": "model",
            "provider": request.provider,
            "model": request.model,
            "symbol": (request.symbol or "").upper() or None,
        }
    }
