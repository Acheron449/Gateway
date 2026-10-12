"""Agentic Trading Lab API — agents, backtest jobs, and performance stats.

Mirrors the Open-Finance-Lab AgenticTrading workflow in miniature:
prototype an agent (model + prompt), backtest it against historical bars,
inspect every decision, and compare runs against baselines with
plain-language statistics.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field, model_validator

from app.auth import CurrentUser, User, get_current_user_optional
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


class MonteCarloRequest(BaseModel):
    run_ids: list[str] = Field(min_length=1, max_length=8)
    simulations: int = Field(default=500, ge=100, le=1000)
    horizon: int = Field(default=252, ge=20, le=1000)
    confidence: float = Field(default=0.9, ge=0.5, le=0.99, allow_inf_nan=False)
    seed: int = Field(default=1, ge=0, le=4_294_967_295)
    start_capital: float = Field(default=10_000, ge=100, le=10_000_000, allow_inf_nan=False)


class ResearchJobRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=20)
    tf: str = Field(default="1d", pattern="^(1d|1h|1wk)$")
    bars: int = Field(default=260, ge=40, le=1000)
    objective: str = Field(min_length=3, max_length=400)
    max_iterations: int = Field(default=3, ge=1, le=10)
    max_model_calls: int = Field(default=8, ge=2, le=40)
    capital: float = Field(default=10_000, ge=100, le=10_000_000, allow_inf_nan=False)
    fee_bps: float = Field(default=5, ge=0, le=100, allow_inf_nan=False)
    slippage_bps: float = Field(default=5, ge=0, le=100, allow_inf_nan=False)


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
    # Strategy-research jobs have a separate owner-checked, allowlisted polling route.
    if job is None or job["kind"] != "lab-backtest":
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Runs & stats
# ---------------------------------------------------------------------------

@router.get("/runs")
async def get_runs(limit: int = 20, user: User | None = Depends(get_current_user_optional)) -> dict[str, Any]:
    """Stored shared runs and runs private to the authenticated caller."""
    runs = lab.visible_runs(user.id if user else None, limit=min(max(limit, 1), lab.MAX_RUNS))
    for run in runs:
        run.pop("owner_user_id", None)
        run.pop("research_job_id", None)
        run.pop("research_iteration", None)
    return {"runs": runs, "summary": lab.runs_summary(runs)}


@router.delete("/runs/{run_id}")
async def remove_run(run_id: str, user: CurrentUser) -> dict[str, Any]:
    if not lab.delete_run(run_id, owner_user_id=user.id):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"deleted": True}


@router.post("/monte-carlo")
async def monte_carlo(request: MonteCarloRequest, user: CurrentUser) -> dict[str, Any]:
    if len(set(request.run_ids)) != len(request.run_ids):
        raise HTTPException(status_code=422, detail="run_ids must be unique")
    visible = {run.get("id"): run for run in lab.visible_runs(user.id, lab.MAX_RUNS)}
    if any(run_id not in visible for run_id in request.run_ids):
        raise HTTPException(status_code=404, detail="Run not found")
    selected = [visible[run_id] for run_id in request.run_ids]
    try:
        return lab.bootstrap_monte_carlo(
            selected,
            simulations=request.simulations,
            horizon=request.horizon,
            confidence=request.confidence,
            seed=request.seed,
            start_capital=request.start_capital,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/research-jobs")
async def create_research_job(request: ResearchJobRequest, user: CurrentUser) -> dict[str, str]:
    provider = llm_svc.canonical_provider(request.provider)
    if provider is None:
        raise HTTPException(status_code=400, detail="Unknown LLM provider")
    try:
        llm_svc.resolve_endpoint(request.provider)
    except llm_svc.LlmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    settings = llm_svc.stored_settings(request.provider)
    configured_models = settings.get("models") or []
    default_model = settings.get("default_model")
    if configured_models and request.model not in configured_models and request.model != default_model:
        raise HTTPException(status_code=400, detail="Choose a configured model for this provider")

    job_meta = {
        "owner_user_id": user.id,
        "provider": request.provider,
        "model": request.model,
        "symbol": request.symbol.strip().upper(),
        "tf": request.tf,
        "bars": request.bars,
        "max_iterations": request.max_iterations,
        "max_model_calls": request.max_model_calls,
        "capital": request.capital,
        "fee_bps": request.fee_bps,
        "slippage_bps": request.slippage_bps,
    }
    job_id = job_store.create("strategy-research", job_meta)
    job_store.update(
        job_id,
        message="Queued research",
        iteration=0,
        iterations=request.max_iterations,
        model_calls=0,
        max_model_calls=request.max_model_calls,
    )

    async def worker(active_id: str) -> None:
        calls = 0

        def checkpoint() -> None:
            if job_store.is_cancelled(active_id):
                raise ResearchCancelled()

        def reserve_model_call() -> None:
            nonlocal calls
            checkpoint()
            if calls >= request.max_model_calls:
                raise ModelCallLimitReached()
            calls += 1
            job_store.update(active_id, model_calls=calls)

        try:
            checkpoint()
            bars = await lab.fetch_bars(request.symbol.strip().upper(), request.tf, request.bars)
            checkpoint()
            if len(bars) < 40:
                raise ValueError(f"Not enough history for {request.symbol} ({len(bars)} bars)")
            completed: list[dict[str, Any]] = []
            for iteration in range(1, request.max_iterations + 1):
                checkpoint()
                remaining = request.max_model_calls - calls
                if remaining < 2:
                    break
                owner_context = research.owner_context(user.id, symbol=request.symbol)
                prior_results = "\n".join(
                    f"Iteration {index + 1}: {item['hypothesis'][:1200]} — return {item['run']['metrics'].get('total_return_pct', 0):.2f}%"
                    for index, item in enumerate(completed)
                )
                proposal_prompt = [
                    {"role": "system", "content": (
                        "Design a bounded historical strategy instruction from the public OHLCV context. "
                        "Return only a concise instruction (maximum 2000 characters); do not request accounts, secrets, tools, or trading actions."
                    )},
                    {"role": "user", "content": (
                        f"Objective: {request.objective[:400]}\nSymbol: {request.symbol.upper()}\n"
                        f"Timeframe: {request.tf}; bars: {len(bars)}\n"
                        f"Public market sample: {lab._window_summary(bars, len(bars) - 1)}\n"
                        f"My research: {owner_context[:8000]}\nPrior iterations from this job: {prior_results[:6000]}"
                    )},
                ]
                reserve_model_call()
                hypothesis = (await llm_svc.chat_once(
                    request.provider,
                    request.model,
                    proposal_prompt,
                    max_tokens=700,
                    timeout=90.0,
                )).strip()[:2000]
                checkpoint()
                decision_budget = request.max_model_calls - calls
                if decision_budget < 1:
                    break
                reserve_decision_call = reserve_model_call
                iteration_decisions = 0

                def reserve_iteration_decision() -> None:
                    nonlocal iteration_decisions
                    if iteration_decisions >= decision_budget:
                        raise ModelCallLimitReached()
                    reserve_decision_call()
                    iteration_decisions += 1

                async def progress(done: int, total: int, message: str) -> None:
                    checkpoint()
                    job_store.update(
                        active_id,
                        iteration=iteration,
                        progress=min(0.98, ((iteration - 1) + done / max(1, total)) / request.max_iterations),
                        message=f"Iteration {iteration}/{request.max_iterations}: {message}",
                        model_calls=calls,
                    )

                run = await lab.run_backtest(
                    {"kind": "llm", "provider": request.provider, "model": request.model, "prompt": hypothesis},
                    symbol=request.symbol.strip().upper(),
                    tf=request.tf,
                    bars_limit=request.bars,
                    capital=request.capital,
                    max_llm_calls=decision_budget,
                    fee_bps=request.fee_bps,
                    slippage_bps=request.slippage_bps,
                    on_progress=progress,
                    research_context=f"{owner_context}\n{prior_results}"[:20_000],
                    reserve_model_call=reserve_iteration_decision,
                    owner_user_id=user.id,
                    research_job_id=active_id,
                    research_iteration=iteration,
                )
                checkpoint()
                doc = research.save_doc(
                    title=f"{request.symbol.upper()} research iteration {iteration}",
                    content=f"Objective: {request.objective}\n\nHypothesis:\n{hypothesis}",
                    source="model",
                    symbol=request.symbol,
                    provider=request.provider,
                    model=request.model,
                    owner_user_id=user.id,
                    research_job_id=active_id,
                    research_iteration=iteration,
                )
                completed.append({"hypothesis": hypothesis, "run": run, "research_id": doc["id"]})
                job_store.update(
                    active_id,
                    result={"iterations": [
                        {"run_id": item["run"]["id"], "research_id": item["research_id"], "hypothesis": item["hypothesis"]}
                        for item in completed
                    ]},
                    iteration=iteration,
                    model_calls=calls,
                    progress=iteration / request.max_iterations,
                    message=f"Completed iteration {iteration}/{request.max_iterations}",
                )
                if calls >= request.max_model_calls:
                    break
            checkpoint()
            job_store.update(active_id, status="succeeded", progress=1.0, message="Research complete")
        except ResearchCancelled:
            job_store.mark_cancelled(active_id)
        except Exception:  # noqa: BLE001 - job_store records the worker failure
            if job_store.is_cancelled(active_id):
                job_store.mark_cancelled(active_id)
            else:
                raise

    job_store.run_async_worker(job_id, worker)
    return {"job_id": job_id}


class ResearchCancelled(Exception):
    pass


class ModelCallLimitReached(Exception):
    pass


@router.get("/research-jobs/{job_id}")
async def get_research_job(job_id: str, user: CurrentUser) -> dict[str, Any]:
    job = job_store.get(job_id)
    if job is None or job.get("kind") != "strategy-research" or job.get("meta", {}).get("owner_user_id") != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        key: job.get(key)
        for key in ("id", "status", "progress", "message", "result", "error", "iteration", "iterations", "model_calls", "max_model_calls")
    }


@router.post("/research-jobs/{job_id}/cancel")
async def cancel_research_job(job_id: str, user: CurrentUser) -> dict[str, Any]:
    job = job_store.get(job_id)
    if job is None or job.get("kind") != "strategy-research" or job.get("meta", {}).get("owner_user_id") != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") not in job_store.TERMINAL_STATUSES:
        job_store.cancel(job_id)
    return {"cancelled": True}


# ---------------------------------------------------------------------------
# Trading log — what the models chose over a user-set duration
# ---------------------------------------------------------------------------

@router.get("/trading-log")
async def get_trading_log(days: int = 30, symbol: Optional[str] = None, user: User | None = Depends(get_current_user_optional)) -> dict[str, Any]:
    """Every recorded model decision inside the window, newest first."""
    from datetime import datetime, timedelta, timezone

    days = max(1, min(int(days), 730))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    wanted = (symbol or "").strip().upper() or None

    entries: list[dict[str, Any]] = []
    runs_seen = 0
    visible = lab.visible_runs(user.id if user else None, limit=lab.MAX_RUNS)
    for run in visible:
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
async def get_research(user: User | None = Depends(get_current_user_optional)) -> dict[str, Any]:
    docs = research.list_docs(user.id if user else None)
    for doc in docs:
        doc.pop("owner_user_id", None)
        doc.pop("research_job_id", None)
        doc.pop("research_iteration", None)
    return {"research": docs}


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
    if not research.delete_doc(doc_id, owner_user_id=user.id):
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
