# Agentic Lab Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate historical strategy, pairs, and iterative research workflows in Agentic Lab while removing the unused Tauric TradingAgents integration and preserving strict per-user ownership for new research-loop artifacts.

**Architecture:** Reuse the current Backtester UI as an Agentic Lab view and existing lab simulator/job/run infrastructure. Add a bounded deterministic bootstrap comparison service plus owner-scoped research jobs and cancellation, storing only public-market strategy research and historical simulations; leave existing shared records readable under current semantics.

**Tech Stack:** FastAPI, Pydantic v2, Python asyncio/thread-safe job store, React 18, TypeScript, Vite, existing filesystem JSON research/run stores.

**Spec:** [2026-10-11-agentic-lab-consolidation-design.md](../specs/2026-10-11-agentic-lab-consolidation-design.md)

## Global Constraints

- Models may access public market context, historical backtests, and their own saved research/logs only; no portfolio, balance, position, vault-secret, broker, or order capability.
- Research jobs and generated artifacts are visible only to verified `CurrentUser.id`; email and client-supplied owner IDs are not authorization.
- Existing unowned Agentic Lab records keep current visibility and rendering behavior.
- Work is historical/research-only; do not auto-promote, deploy, or execute model strategies.
- Iteration count, total model calls, requested bars, Monte Carlo simulations/horizon, and returned chart points are bounded and validated server-side.
- Pair Monte Carlo is excluded until an appropriate unified equity-return series exists.
- Do not alter unrelated model-picker, calendar/provider, or scanner/command-bar systems in this project.

## Review Focus

- Malformed/non-finite Monte Carlo inputs or flat/invalid equity series must fail cleanly rather than produce misleading paths.
- Ownership checks must apply to polling, cancellation, every run/research/log collection read, and Monte Carlo input resolution; test cross-user 404/omission.
- A call cap must not be exceeded even at an iteration boundary or when generation fails/retries.
- Cancellation during provider work must stop at the next safe checkpoint and leave prior completed iterations intact.
- Legacy shared records and pairs runs must continue rendering unchanged; legacy `/app/backtests` links must open the Backtests tab.

---

### Task 1: Remove dedicated TradingAgents integration

**Files:**
- Delete: `quant-app-v1/backend/app/api/v1/agents.py`
- Delete: `quant-app-v1/backend/app/services/trading_agents_service.py`
- Modify: `quant-app-v1/backend/app/api/main.py`
- Modify: `quant-app-v1/backend/Dockerfile`
- Modify: `requirements.txt`
- Modify: `quant-app-v1/frontend/src/components/layout/AgenticLab.tsx`
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`
- Modify: `docs/status.md`
- Test: `quant-app-v1/backend/tests/test_agentic_lab.py`

**Interfaces:** no new interfaces. Remove the `/agents/trading-agents*` API and its router; preserve shared LLM providers and Agentic Lab APIs.

- [x] **Step 1: Add removal contract tests**

Add tests asserting all dedicated `/agents/*` routes (`/agents/trading-agents`, `/agents/trading-agents/run`, `/agents/jobs`, `/agents/jobs/{job_id}`) are absent, while `/agentic-lab/backtest` and `/llm/providers` remain registered. Confirm route test setup uses the existing FastAPI app and authentication override conventions.

- [x] **Step 2: Verify tests fail before removal**

Run: `pytest backend/tests/test_agentic_lab.py -q`
Expected: new route-exclusion assertions fail because `/agents` is currently included.

- [x] **Step 3: Remove dedicated feature wiring and stale UI**

Remove the router import/include and TradingAgents-only component tab/state/effect/callback/render block. Remove the external package install and git build dependency if otherwise unused. Remove only Tauric-specific CSS and update `docs/status.md` so it no longer describes the integration as complete or Docker as requiring its install. Do not remove common model-provider functionality.

- [x] **Step 4: Run removal and adjacent tests**

Run focused Agentic Lab, deploy-hardening, auth, and job-store suites. Removed `/agents/trading-agents` responds 404; shared `/agentic-lab/*` and `/llm/providers` routes remain registered and available.

### Task 2: Deterministic bounded Monte Carlo service/API

**Files:**
- Modify: `quant-app-v1/backend/app/services/lab_backtest.py`
- Modify: `quant-app-v1/backend/app/api/v1/agentic_lab.py`
- Test: `quant-app-v1/backend/tests/test_agentic_lab.py`

**Interfaces:**
- Add a pure `bootstrap_monte_carlo(runs, *, simulations, horizon, confidence, seed, start_capital) -> dict` helper. Accept per-run `bar_returns` with at most 1,000 finite simple returns, each greater than -1. Each eligible run returns run identity, median and lower/upper confidence values per time step, and total simulation metadata.
- Add authenticated `POST /agentic-lab/monte-carlo`; accept at most 8 selected run IDs, simulations 100–1000, horizon 20–1000, confidence 0.5–0.99, bounded seed, and start capital ≥100. Cap aggregate simulations × horizon at 4,000,000 and return at most 120 sampled chart points per run.
- No external library dependency; use existing Python `random.Random` and pure numeric functions.

- [x] **Step 1: Add Monte Carlo tests**

Test fixed-seed exact repeatability; median/band ordering and path length; distinct output per distinct input returns; persist full per-bar returns before chart downsampling; reject missing legacy return series, returns ≤ -1, and non-finite values; reject pairs-only selections, unknown IDs, empty selections, invalid confidence/count/horizon, oversized run selections, and excess aggregate work; normalize output to requested start capital.

- [x] **Step 2: Run focused tests and confirm failure**

Focused Monte Carlo coverage was added and run with the relevant Agentic Lab test module; the implemented path satisfies deterministic, input-bound, and visibility assertions.

- [x] **Step 3: Implement pure bootstrap math using the full persisted equity curve**

Persist up to 1,000 full-resolution simple per-bar returns on every newly generated single-strategy run before its chart/equity display downsampling. Seed an independent deterministic RNG per run using the supplied seed and stable run identity. Bootstrap those returns with replacement for the bounded horizon, compound from the common start capital, and compute median and central lower/upper quantiles. Reject pairs, legacy runs without return data, and any non-finite return or return ≤ -1. Never approximate them using display-downsampled curves. Enforce run/simulation/horizon and aggregate 4,000,000-point caps.

- [x] **Step 4: Add the authenticated API route and validate inputs**

Resolve run IDs only from caller-visible runs (shared unowned records and owner-owned private records). Return a clear 422/400 for unsupported pairs or insufficient returns. The route does not expose another user's private run.

- [x] **Step 5: Run focused tests**

Focused Agentic Lab test module passes as part of the 61-test verified set.

### Task 3: Add owner-scoped cancelable iterative research jobs

**Files:**
- Modify: `quant-app-v1/backend/app/services/job_store.py`
- Modify: `quant-app-v1/backend/app/services/research_store.py`
- Modify: `quant-app-v1/backend/app/services/lab_backtest.py`
- Modify: `quant-app-v1/backend/app/api/v1/agentic_lab.py`
- Test: `quant-app-v1/backend/tests/test_agentic_lab.py`
- Test: create `quant-app-v1/backend/tests/test_job_store.py`

**Interfaces:**
- Job store adds `cancel(job_id) -> bool`, cancellation state/event, and terminal status `cancelled`; a worker can check `is_cancelled(job_id) -> bool` at safe boundaries.
- Add `POST /agentic-lab/research-jobs` with `ResearchJobRequest`: provider, model, symbol, `tf` in `1d|1h|1wk`, `bars` 40–1000, objective 3–400 chars, `max_iterations` 1–10, `max_model_calls` 2–40, capital 100–10,000,000, and optional bounded fee/slippage assumptions. Each iteration needs at least two reserved calls: a proposal call and one simulator decision call.
- Add authenticated `GET /agentic-lab/research-jobs/{job_id}` and `POST /agentic-lab/research-jobs/{job_id}/cancel`; 404 for unknown/non-owner jobs. Return an allowlisted job shape (`id`, `status`, `progress`, `message`, `result`, `error`, `iteration`, `iterations`, `model_calls`, `max_model_calls`) and never serialize internal owner/job metadata.
- Add `owner_user_id`, `research_job_id`, `research_iteration` optional run fields and `owner_user_id`, `research_job_id`, `research_iteration` optional research-doc fields. Add authenticated `OptionalUser` handling to run/research/trading-log list reads: unowned legacy rows remain shared, private rows are returned only to their owner.

- [x] **Step 1: Add cancellation and ownership unit/API tests**

Cover job cancellation idempotency, terminal-state behavior, polling/cancel cross-user 404, invalid limits, provider/model preflight, budget reservation before every proposal/simulator model call, cancellation checkpoints, run/doc tags, and collection/trading-log/Monte Carlo isolation for private artifacts. Assert prompts contain only public bar data/objective and same-owner research, never portfolio/broker or other-user data.

- [x] **Step 2: Run tests to confirm failures**

Focused job-store and Agentic Lab coverage exists and passed as part of the verified test set.

- [x] **Step 3: Implement safe job cancellation state**

Store per-job `threading.Event` outside public job serialization. A cancel request sets an internal cancellation flag/event; the worker marks the job `cancelled` at the next safe checkpoint. Ensure worker completion/exceptions after cancellation do not overwrite the terminal cancellation state. Job polling returns an allowlisted response without owner/internal metadata.

- [x] **Step 4: Add ownership-aware research and run persistence/query helpers**

Persist optional `owner_user_id`, `research_job_id`, and `research_iteration`. Keep records without an owner shared. Filter private generated records in list/log reads; only owner may delete generated private research/runs. Iterative jobs supply owner-scoped context explicitly rather than the shared global context.

- [x] **Step 5: Add iterative job API and runner**

Validate the provider/model and use only public market history, the caller's research, and this job's prior outputs. Reserve the shared model-call budget immediately before each proposal and simulator request. Save successful iteration artifacts owner-only; expose no portfolio, vault, broker, or order capabilities.

- [x] **Step 6: Add authenticated job polling/cancel routes and secure related reads**

Enforce user ownership and 404 for cross-user job access. Filter private runs/documents/logs and authorize Monte Carlo IDs against caller-visible runs.

- [x] **Step 7: Run focused and security-related backend tests**

Run the five focused test modules recorded in Verification; all 61 tests pass, including ownership, cancellation, call budget and existing auth coverage.

### Task 4: Consolidate the Agentic Lab UI and render Monte Carlo comparison

**Files:**
- Modify: `quant-app-v1/frontend/src/components/layout/AgenticLab.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/Backtester.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/CenterCanvas.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/LeftSidebar.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/Navigation.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/CommandPalette.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/RightInspector.tsx`
- Modify: `quant-app-v1/frontend/src/lib/views.ts`
- Modify: `quant-app-v1/frontend/src/App.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/AiHarness.tsx`
- Modify: `quant-app-v1/frontend/src/styles/app.css`
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`

**Interfaces:**
- `AgenticLab` tabs: `dashboard`, `research`, `log`, `backtests`, `pairs`.
- AgenticLab owns the fetched `runs`, `loading`, `error`, and refresh callback; the Backtester child consumes these props and does not fetch a duplicate history or own a second run list. Remove its embedded pairs launcher.
- Deep link `/app/agentic-lab?tab=backtests`; AgenticLab initializes from the query parameter. Legacy `/app/backtests` redirects to this URL before normal invalid-view handling.
- Update old Backtester deep-links in the AI harness to point into Agentic Lab.
- Research form accepts objective, public market parameters, iteration cap, and total model-call cap; the job panel shows progress/call counts and a cancel action.

- [x] **Step 1: Consolidate existing views and remove duplicate entry points**

Agentic Lab owns the single run-list fetch. Backtester receives runs/loading/error/refresh props. The Pairs launcher is mounted only in the Cointegration Pairs tab. Backtester navigation is removed; legacy `/app/backtests` deep links redirect to the Backtests tab.

- [x] **Step 2: Add selected-run Monte Carlo comparison UI**

The Backtests view supports selected eligible single-strategy runs, bounded simulation/horizon/confidence settings, deterministic distinct colors keyed by run ID, a strategy legend, and an explicit historical-bootstrap disclaimer. Unsupported pair/legacy runs are explained.

- [x] **Step 3: Add research-job launcher, progress, and cancellation UI**

The Research tab uses the selected configured provider/model, public symbol/timeframe/bars, iteration and model-call caps; it displays job status/progress/results and offers cooperative cancellation.

- [x] **Step 4: Verify TypeScript/build**

`npm run build` from `quant-app-v1/frontend` passed (Vite reports its >500 kB chunk advisory).

### Task 5: Validate API, UI, docs, and final integration

**Files:**
- Modify: `docs/status.md`
- Modify: `docs/superpowers/specs/2026-10-11-pairs-backtest-foundation-design.md`
- Modify: `docs/superpowers/plans/2026-10-11-pairs-backtest-foundation.md`
- Test: relevant backend and frontend verification suites

- [x] **Step 1: Update project status and superseded pairs-doc intent**

The status and pairs docs describe the unified lab and no longer claim a standalone Backtester launcher. Independent model discovery, calendar/provider and scanner changes remain deferred.

- [x] **Step 2: Run full relevant backend suite (attempted; environment blocked collection)**

`pytest -q` was attempted. The full suite is blocked during collection (65 collection errors): local SciPy `_propack._spropack` loader, an existing Pydantic StrategySpec regression-test `Any` forward-reference error, and missing/incompatible optional dependencies in discovered vendored Kronos/TradingAgents tests. A retry omitting the pairs module still stops at the StrategySpec collection error. The focused five-module suite passes (61 tests). Pair-specific tests could not be executed successfully in this local environment.

- [x] **Step 3: Run frontend build and interface smoke test**

`npm run build` passed. Browser smoke was run against local Vite and FastAPI servers: the five tabs render; Backtests shows run history and Monte Carlo controls/disclaimer; Cointegration Pairs contains the launcher; the legacy `/app/backtests` URL redirects correctly. API-backed lab routes and health/OpenAPI return 200. External quote/calendar requests have provider-dependent 503 responses; no real model call was submitted.

- [x] **Step 4: Verify no hidden dependency or route remains**

OpenAPI confirms the Monte Carlo/research endpoints and shared LLM route; removed `/agents/trading-agents` returns 404. `git grep` found no remaining application wiring or dependency for the removed Tauric integration (the contract test keeps the legacy path as a negative assertion). Ignored vendor data was not deleted.

- [x] **Step 5: Final checks**

`git diff --check` passed after final documentation updates. Docker verification was unavailable: this environment has no Docker CLI. The tracked production `dist/index.html` artifact is not part of this source change; the build changed generated chunk names locally, then its tracked manifest references were restored.

## Verification and completion record (2026-10-12)

- Focused backend command: `JWT_SECRET_KEY=test-secret PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_agentic_lab.py tests/test_job_store.py tests/test_deploy_hardening.py tests/test_auth_preferences.py tests/test_journal_and_vault.py` from `quant-app-v1/backend`; **61 passed**.
- Frontend: `npm run build` succeeded; TypeScript and Vite completed, with the existing chunk-size advisory.
- Full-suite failures are collection/environment blockers, not counted as passes. Pair backtest focused module is among modules whose import currently fails due to this environment's SciPy extension loader issue.
- Interface smoke: verified all five tabs, pair-launcher placement, Monte Carlo result area/disclosure, and the legacy redirect in a browser against local servers. Health, OpenAPI, agent/research/run list, and provider calls were checked. Calendar/quote providers included 503 responses; no third-party model credentials were used.
- `git diff --check`: passed after documentation update. Docker: not run (CLI unavailable).

## Deferred subprojects from the original request

Do not mark these complete as part of Agentic Lab consolidation:
1. Provider model-picker auto-discovery and free-only catalog/filter.
2. Add yfinance as a calendar provider and remove Financial Modeling Prep from provider registry/chain.
3. Move Scanner functionality into the search/command palette and remove duplicate navigation/features.

These are architecturally separate changes and need their own approved designs and implementation plans.
