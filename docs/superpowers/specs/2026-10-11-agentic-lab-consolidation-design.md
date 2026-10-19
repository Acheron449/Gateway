# Agentic Lab Consolidation — Design

## Goal

Make Agentic Lab the single workspace for model strategy experiments, pairs research, saved backtests, comparisons, and bounded iterative strategy research. Remove the unused Tauric Research TradingAgents integration without granting models access to private portfolio data or trading actions.

## User decisions

- Agentic Lab/backtester consolidation is the first independently delivered project; model discovery, calendar/provider cleanup, and scanner/command search remain later projects.
- Models receive bounded, user-initiated research capabilities: public market context, historical backtests, research documents, and run/trading logs only. No portfolio/funds access and no order placement.
- Iteration count and total model-call cap are configurable. Jobs show progress and can be cancelled.
- Jobs and their generated runs/research artifacts are private to the authenticated user who started them. Existing Agentic Lab history ownership semantics remain unchanged.
- Monte Carlo comparison uses completed single-strategy runs; pair runs are excluded until a compatible equity-return series is supported.
- The Backtester nav item is removed; old `/app/backtests` links redirect to `/app/agentic-lab?tab=backtests`, and Agentic Lab initializes its Backtests tab from that query parameter.
- Remove TradingAgents UI, service/API/router, and Docker installation completely after repository dependency analysis found no internal clients. External consumers of the dedicated API are unknown and will break; user explicitly accepted complete removal.

## Existing architecture

- `frontend/src/components/layout/AgenticLab.tsx` owns Agentic Lab tabs, provider selection, agent jobs, research, run summaries, trading logs, and performance cards; `Backtester.tsx` is the current separate run history/detail view.
- `frontend/src/components/layout/Backtester.tsx` is a separate full-screen run history/details UI and mounts `PairsBacktestLauncher`, duplicating the launcher already present in the pairs surface.
- `backend/app/api/v1/agentic_lab.py` and `backend/app/services/lab_backtest.py` own baseline/LLM/pairs job and persisted run behavior. `pairs_backtest.py` provides deterministic pair simulation and walk-forward outputs.
- `backend/app/services/job_store.py` is an in-memory polling job store; it currently supports success/failure but has no cancellation state.
- `backend/app/engine/backtester.py` declares Monte Carlo configuration/result fields, but no implemented Monte Carlo path exists. The selected implementation will target Agentic Lab runs and not duplicate this unused engine configuration.

## Proposed architecture

### Agentic Lab tabs and navigation

Agentic Lab tabs become `LLMs`, `Research`, `Trading Log`, `Backtests`, and `Cointegration Pairs`. The current Performance view is folded into Backtests, where saved-run selection, run detail, metrics, run-to-run comparisons, and Monte Carlo visualization share one result surface. Agentic Lab owns the run list and passes it with a refresh callback to the Backtests child, so the child does not fetch a duplicate run list. Reuse `Backtester` as a child/view component rather than copying its rendering or duplicating simulation behavior. Mount `PairsBacktestLauncher` only in Cointegration Pairs; completed pairs results remain selectable in Backtests, including their spread, fills, and walk-forward detail. Remove the separate Backtester view/navigation item. A `/app/backtests` legacy route redirects to `/app/agentic-lab?tab=backtests`; Agentic Lab initializes its active tab from that query parameter.

### Monte Carlo visualization

Add a deterministic, bounded Monte Carlo bootstrap utility in the Agentic Lab service. Newly generated single-strategy runs persist `bar_returns`, a full-resolution, bounded list of simple per-bar returns (maximum 1,000 values), derived from the full equity curve before its chart downsampling. For each selected completed non-pairs run with valid `bar_returns`, resample with replacement, normalize paths to the same starting capital, then plot the median simulated equity path and a central confidence band. Each run gets a distinct deterministic color and legend entry. Inputs are capped to at most 8 runs, 1,000 simulations, 1,000 horizon steps, and 4,000,000 total simulation-points per request. Legacy runs without `bar_returns`, invalid return data, and pair runs are rejected or excluded explicitly; do not approximate them using a display-downsampled equity curve. Label the visualizer as a historical-return resampling simulation, not a forecast or proof against overfitting.

### Iterative research

Add an authenticated Agentic Lab operation that creates a `strategy-research` job. Its request fixes the provider/model, symbol, timeframe, bar count, starting capital, objective prompt, maximum iterations (1–10), and total model-call budget (2–40). Each iteration must have at least two calls available: a strategy proposal call and at least one simulator decision call. Validate finite ranges and the configured model endpoint before starting. The runner gathers only public market history/context, asks the selected model to propose/refine a structured strategy instruction, and passes that proposal to the existing Agentic Lab historical simulator. Thread a synchronous `reserve_model_call: Callable[[], None] | None` callback (from `typing.Callable`) through `run_backtest` and `llm_targets`, invoking it immediately before each outbound `chat_once` request (proposal and every simulator decision) so the cap cannot be exceeded. Save each bounded hypothesis and backtest as normal run/research records tagged with `research_job_id`, `research_iteration`, and the verified owner user ID. Those new artifacts are visible only to their owner through list/log APIs; older shared Agentic Lab records retain current visibility. For this loop, supply only owner-owned research and outputs already produced by the same job; do not use other users' research documents as context. Do not expose portfolio, balances, positions, vault secrets, broker APIs, or order tools to this runner.

Private ownership must be enforced at API reads, not just obscured in the UI. Persist the authenticated owner's stable `CurrentUser.id` on the job and each generated artifact, require authentication for research-job polling/cancellation, return 404 for another user's job, and filter generated private runs/documents from the runs, research, and trading-log collection responses unless the caller owns them. Restrict deletion of private generated research to its owner. Existing unowned runs/documents remain visible as they are today. Never use email or a client-supplied owner field for authorization.

Support cancellation through a thread-safe cancellation event associated with the job. The loop checks cancellation and caps between market retrieval, each model request, and each backtest iteration. Update progress with iteration and call counters. Stopping occurs on cancel, iteration cap, model-call cap, or a surfaced provider/simulation error. Do not automatically select, promote, deploy, or execute the best strategy.

### TradingAgents removal

Remove the dedicated React tab/state/polling, `/agents` router module, service module, API import/registration, and external Git install from the backend Docker build. Remove stale completion claims from `docs/status.md`. The root requirements' explanatory comments are also removed. Preserve shared provider/LLM infrastructure, Agentic Lab's own model runner, and the unrelated `backtest.py` API (which is a disabled legacy typed-StrategySpec surface, not the Tauric service).

## API and storage contracts

- Existing `/agentic-lab/runs`, `/agentic-lab/backtest`, and pair-result schemas remain backward compatible.
- Add authenticated `POST /agentic-lab/research-jobs`, `GET /agentic-lab/research-jobs/{job_id}`, and `POST /agentic-lab/research-jobs/{job_id}/cancel`. Check ownership against verified `CurrentUser.id` and return 404 for another user's job.
- Add optional `research_context: str | None`, `reserve_model_call: Callable[[], None] | None`, `owner_user_id: str | None`, `research_job_id: str | None`, and `research_iteration: int | None` keyword parameters to `lab_backtest.run_backtest`; existing callers retain behavior when omitted. Never return `owner_user_id` in API payloads.
- Persist `owner_user_id`, `research_job_id`, and `research_iteration` on private runs/research records; persist `bar_returns: list[float]` of at most 1,000 full-resolution simple returns on newly generated single-strategy runs. Existing unowned records retain shared visibility and rendering.
- Use `OptionalUser` on run/research/trading-log list routes: shared legacy rows remain shared; private rows are only returned to their owner. Allow private generated run/research deletion only by the owner. Keep legacy global research context limited to unowned/shared documents; iterative jobs supply owner-scoped context explicitly.
- The research-job poll response is allowlisted and excludes internal owner and job metadata. The call budget is 2–40 total model calls; every iteration reserves one proposal call and at least one simulator decision call before starting, and the simulator receives only the remaining decision-call allowance.
- Add authenticated `POST /agentic-lab/monte-carlo` accepting at most 8 visible run IDs, 100–1,000 simulations, 20–1,000 horizon bars, confidence 0.5–0.99, seed, and starting capital. Returns must be finite and greater than -1. Cap aggregate simulations × horizon at 4,000,000 and return at most 120 samples for median/band series. Pair runs and legacy runs without `bar_returns` are unsupported, not approximated from display curves.
- Keep all artifacts bounded and JSON-serializable. Never persist credentials, prompts containing secrets, or raw private account data in job metadata.

## Error and resource behavior

- Reject missing/unconfigured models, malformed limits, unknown or non-visible run IDs, pairs in Monte Carlo, and unsupported/no-return histories with precise 4xx errors.
- Provider/network failures terminate a research job with a useful failure message; completed iterations remain visible to their owner.
- A cancel request sets a cooperative flag/event; the worker marks the job `cancelled` at its next safe checkpoint. Cancellation is idempotent and terminal jobs cannot be restarted.
- Cap iterations, calls, strategy prompt sizes, requested bars, bootstrap simulations, and returned chart points. No unbounded background loop.

## Tests and acceptance criteria

- Backend unit tests: bootstrap reproducibility for a fixed seed; median/band ordering and dimensions; full-resolution `bar_returns` persistence before chart downsampling; invalid/too-long returns; legacy records without returns; pair-run exclusion; run-count, simulation, horizon, and aggregate work caps.
- API tests: authenticated research-job creation and ownership-scoped polling/cancel; another user receives 404; invalid caps; job call budget enforcement including strategy proposal and every simulator decision; cancellation between iterations; private artifacts are excluded from other users' run/research/trading-log/Monte Carlo reads; model-run artifacts carry the parent job, iteration, and owner; no account, broker, or other-user research context reaches model prompts.
- Frontend build/typecheck and interface test: five Agentic Lab tabs; pairs launcher only in Cointegration Pairs; existing backtest history and pair details render inside Backtests; legacy `/app/backtests` redirects to Backtests tab; multi-run Monte Carlo shows distinctly colored strategy entries; loop progress/cancel/limits are usable.
- Existing baseline, LLM, pair, auth, and run history tests continue passing.
- Verify no tracked TradingAgents package/API/service/UI wiring remains other than historical attribution in immutable docs if any; update status docs to identify unfinished items accurately.

## Out of scope

Automatic model discovery/free-price filtering, yfinance calendar source, Financial Modeling Prep removal, and moving Scanner into the command bar remain separate projects. Iterative research receives only its bounded owner-scoped context; do not loosen general chat system safety rules or add private account-data/order capabilities as part of this design.
