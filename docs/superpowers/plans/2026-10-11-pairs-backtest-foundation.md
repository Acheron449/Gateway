# Pairs Backtester Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship deterministic cointegration-filtered pairs backtests using a transparent OHLCV-derived synthetic order book and chronological walk-forward evaluation, accessible from both Agentic Lab and Backtester.

**Architecture:** Extend the existing Agentic Lab run job path with a pairs strategy, retaining current baseline/LLM behavior. Put pair math and execution in a focused service module, fetch both histories with the current Yahoo/yfinance pipeline, serialize pair/walk-forward results into existing run storage, then add one shared launcher and conditional run-detail presentation in both UI surfaces.

**Tech Stack:** Python 3.11/FastAPI/Pydantic, existing async market provider service, statsmodels Engle–Granger test, pytest; React 18/TypeScript/Vite.

**Spec:** [2026-10-11-pairs-backtest-foundation-design.md](../specs/2026-10-11-pairs-backtest-foundation-design.md)

## Global Constraints

- Pair prices are valid positive closes, timestamp aligned; insufficient common history must fail clearly.
- Fit hedge ratios, cointegration tests and residual standardization using only past/training observations.
- Fill pair trades no earlier than the next bar open; never claim OHLCV estimates are historical Level-2 replay.
- Preserve existing baseline/LLM request and run behavior.
- Report that walk-forward validation helps evaluate out-of-sample behavior but does not prevent all overfitting or ensure profit.
- Keep existing run persistence cap and payload bounded/JSON serializable.
- Declare a pinned compatible statsmodels version in backend and root requirements only after verifying Python/SciPy compatibility.

## Review Focus

- Timestamp mismatch, missing closes, duplicate bars or unsorted histories — API/service tests must confirm deterministic alignment and explicit insufficient-data errors.
- Cointegration p-value and OLS training windows — unit tests must prove no held-out/future values affect fold models.
- Missing/zero volume or one constrained leg — tests must prove the pair is left unfilled or both legs are reduced proportionally, never accidentally naked.
- Fees, slippage and synthetic spread — tests must prove costs are applied per leg and execution metadata is serializable.
- Baseline/LLM regression risk and old saved runs — tests and UI checks must prove existing behavior remains functional when pair fields are absent.

---

## File Map

- Create `quant-app-v1/backend/app/services/pairs_backtest.py`: pair alignment, rolling estimation, Engle–Granger qualification, z-score signals, synthetic paired fills, metrics and fold runner.
- Modify `quant-app-v1/backend/app/services/lab_backtest.py`: fetch pair histories, dispatch `kind="pairs"`, adapt/persist result into existing run format.
- Modify `quant-app-v1/backend/app/api/v1/agentic_lab.py`: typed validated pair parameters, job metadata, provider fetch orchestration and result routing.
- Modify `quant-app-v1/backend/requirements.txt` and root `requirements.txt`: add pinned compatible statsmodels dependency only after dependency compatibility check.
- Create `quant-app-v1/backend/tests/test_pairs_backtest.py`: statistical causality, execution, alignment and folds.
- Modify `quant-app-v1/backend/tests/test_agentic_lab.py` or create API-specific tests under `quant-app-v1/backend/tests/`: pair run persistence/API behavior and backwards compatibility.
- Create `quant-app-v1/frontend/src/components/features/PairsBacktestLauncher.tsx`: shared configuration, submission, polling and refresh callback.
- Modify `quant-app-v1/frontend/src/components/layout/AgenticLab.tsx`: mount shared launcher.
- Modify `quant-app-v1/frontend/src/components/layout/Backtester.tsx`: mount shared launcher and render pair/fold/fill details.
- Modify `quant-app-v1/frontend/src/styles/extensions.css`: responsive launcher/result styles.

## Interfaces

- `run_pairs_backtest(bars_a, bars_b, *, symbol_a, symbol_b, tf, capital, config) -> dict[str, Any]` returns `pair_series`, paired `trades`, `equity_curve`, `walk_forward`, `execution_model`, `metrics`, and an explicit synthetic-book caveat.
- Pair request config keys are `lookback`, `entry_z`, `exit_z`, `cointegration_pvalue`, `walk_forward_folds`, `spread_floor_bps`, `range_factor`, and `participation_rate`.
- Agentic Lab POST remains `/agentic-lab/backtest`; jobs continue polling `/agentic-lab/jobs/{id}`; runs continue loading from `/agentic-lab/runs`.
- Pair run record uses `kind="pairs"`, symbols `symbol`/`symbol_b`, `pair_config`, and bounded `pair_series` plus fold/fill data.
- Shared frontend launcher accepts `onComplete: () => void` and optional initial symbol; both mounts use the same API schema and job flow.

### Task 1: Verify statsmodels compatibility and add causal pair math with unit tests

**Files:**
- Create: `quant-app-v1/backend/app/services/pairs_backtest.py`
- Create: `quant-app-v1/backend/tests/test_pairs_backtest.py`
- Modify: `quant-app-v1/backend/requirements.txt`
- Modify: `requirements.txt`

- [ ] Inspect supported Python version, root constraints, backend deployment pins and installed SciPy; install/test a compatible pinned statsmodels candidate in a project-local test environment without altering unrelated locks.
- [ ] Write failing tests for positive-price/timestamp alignment, OLS beta/intercept, cointegrated-vs-independent Engle–Granger gating, z-score threshold direction, and no future-data leakage.
- [ ] Run the focused test module and verify failures demonstrate missing pair behavior.
- [ ] Implement pure functions for configuration validation, aligned logs, OLS fit, Engle–Granger qualification and causal rolling spread/z-score state.
- [ ] Declare the exact tested statsmodels version in both requirements files; do not add a frontend dependency.
- [ ] Run `pytest backend/tests/test_pairs_backtest.py -q` from `quant-app-v1` using the project test environment; expect all unit tests pass.

### Task 2: Implement synthetic paired book, cash/equity accounting and walk-forward folds

**Files:**
- Modify: `quant-app-v1/backend/app/services/pairs_backtest.py`
- Test: `quant-app-v1/backend/tests/test_pairs_backtest.py`

- [ ] Add tests for next-bar-open fills, floor-plus-range synthetic spread, per-leg fees/slippage, zero/missing volume, constrained-leg proportional fills, pair close/reversal and forced close at fold end.
- [ ] Add tests for chronological non-overlapping folds, fold estimator reset, training-only fit/cointegration, out-of-sample metrics and explicit insufficient-fold output.
- [ ] Run focused tests and confirm the missing execution/fold assertions fail.
- [ ] Implement paired order sizing/capacity and market-value accounting so both legs scale together; expose fill status, modeled spread, requested/filled quantity and prices.
- [ ] Implement walk-forward partitioning with training-only model estimates, test-only execution, bounded per-fold outputs and aggregate OOS metrics.
- [ ] Run focused tests; expect every fill, accounting and fold assertion to pass.

### Task 3: Route and persist pairs jobs without changing current run kinds

**Files:**
- Modify: `quant-app-v1/backend/app/api/v1/agentic_lab.py`
- Modify: `quant-app-v1/backend/app/services/lab_backtest.py`
- Modify: `quant-app-v1/backend/tests/test_agentic_lab.py`
- Modify/Create: API tests following the existing test harness

- [ ] Add failing tests proving pair request validation rejects duplicate symbols, bad thresholds and invalid folds; valid pair jobs fetch both series and store serializable pair outputs; baseline and LLM payloads remain accepted as before.
- [ ] Run focused API/service tests to verify failures.
- [ ] Add Pydantic pair config and `symbol_b`; constrain config ranges and enforce pair-required fields when `kind="pairs"`.
- [ ] Extend market bar normalization/fetch so volume is carried through without inventing missing values; fetch two symbols, timestamp-align in the pair service, return useful insufficient-overlap errors.
- [ ] Dispatch pairs from the existing worker, update job progress, normalize display fields, store `pair_config`, `pair_series`, fills, fold data and synthetic limitation.
- [ ] Ensure baseline/LLM remain on their existing service/simulator paths and that pair failures mark jobs failed with a useful message.
- [ ] Run relevant API/service test modules; expect valid job completion/persistence, invalid input rejection, and old strategy regression tests pass.

### Task 4: Shared pair launcher and saved run visualization

**Files:**
- Create: `quant-app-v1/frontend/src/components/features/PairsBacktestLauncher.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/AgenticLab.tsx`
- Modify: `quant-app-v1/frontend/src/components/layout/Backtester.tsx`
- Modify: `quant-app-v1/frontend/src/styles/extensions.css`

- [ ] Add or extend frontend tests if infrastructure is present; otherwise record an interface test checklist before coding.
- [ ] Create a shared responsive launcher for two symbols, lookback/thresholds, fold count and synthetic-book assumptions, using the existing auth headers, API base, job polling and explicit error states.
- [ ] Mount the launcher in Agentic Lab and Backtester and refresh each surface after a successful run without changing the run-list API.
- [ ] Extend `BtRun` with optional pair output so legacy records remain safe; add pair-specific title, spread/z-score chart with entry/exit reference levels, fold summary, paired fills and unavoidable synthetic-L2 caveat.
- [ ] Add focused CSS and mobile layout behavior matching existing design conventions.
- [ ] Run `npm run build` from `quant-app-v1/frontend`; expect TypeScript and Vite build to succeed.
- [ ] Launch/reuse the local frontend and verify both entry points can submit/observe the same pair run, results render with all required disclosures, and old saved runs still render.

### Task 5: Final integrated verification and spec review

**Files:**
- All above

- [ ] Run all relevant backend pair/agentic tests and the frontend build.
- [ ] Run `git diff --check` and inspect exact changed hunks.
- [ ] Verify outputs against the design: causal beta and cointegration, synthetic volume-capped paired fills, chronological OOS folds, shared launcher on both surfaces, persisted run rendering, old run compatibility.
- [ ] Report limitations such as unavailable historical volume, unavailable providers, or blocked live interface checks; do not claim performance improvement without measured representative data.
