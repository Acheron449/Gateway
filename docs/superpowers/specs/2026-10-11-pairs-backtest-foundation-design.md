# Pairs Backtester Foundation — Design

## Goal

Provide a reproducible, deterministic pairs-trading backtest based on rolling cointegration and spread reversion, with a transparent OHLCV-derived synthetic order book and chronological out-of-sample walk-forward evaluation. Launch the shared flow from Agentic Lab and Backtester, and persist the results in the existing run history for user and LLM inspection/training.

## Scope

### In scope

- Add deterministic strategy kind `pairs` to the Agentic Lab backtest job flow.
- User-selectable symbols A/B, timeframe/history length, rolling lookback, z-score entry/exit thresholds, cointegration p-value threshold, walk-forward fold count, order-book spread floor/range factor, and maximum participation fraction.
- Pair data acquisition through the existing historical market-data path; timestamp-align the two assets and reject insufficient overlapping data.
- Past-only rolling OLS hedge ratios and an Engle–Granger cointegration test. Trade only when the test p-value is below the configured threshold.
- Build the spread as `log(A) - beta * log(B)`. Enter on z-score threshold crossings and close when the spread reverts through the exit threshold.
- Dollar-neutral pair legs: high spread => short A / long B; low spread => long A / short B.
- Synthetic OHLCV-derived limit-order-book execution: estimate spread from a configurable floor plus candle range contribution; cap order size by a configurable portion of bar volume; execute on the next bar's open; apply existing per-leg fees and slippage. Record filled/partial/unfilled status, modeled spread, capacity and fill prices. Label results synthetic and do not represent them as historical Level-2 data.
- Walk-forward evaluation with chronological folds. Each fold uses its training partition to estimate hedge ratio and model settings and evaluates signals/execution on a later held-out partition. No future values may influence training estimates. Record fold dates, cointegration p-value/status, observations, and out-of-sample metrics.
- Persist the run in existing Agentic Lab run storage and expose it in the existing Backtester results view.
- Shared pairs-run launcher reachable from both Agentic Lab and Backtester, using the same API/job path.

### Deferred

- LLM-driven pair position selection.
- Applying walk-forward validation to LLM historical forecasts or live forecasts; this requires separate provider-call/cost controls and a durable live prediction log.
- Real historical Level-2 feed integration.
- Automated parameter optimization or promises that walk-forward validation prevents overfitting. It diagnoses out-of-sample behavior; it cannot guarantee future performance.
- Options/Greeks, calendar/Kronos, provider endpoint, strategy studio, chat and other separately requested subsystems.

## Signal and execution rules

- Align bars on timestamp and use only valid, positive close prices.
- For each eligible decision bar, calculate beta from the trailing training window ending before the decision bar. Use log prices and ordinary least squares with an intercept. The intercept is included in residual calculation; report beta and p-value.
- Run an Engle–Granger test on the training window only. No new positions are opened unless the p-value is strictly less than the configured threshold. Close outstanding positions when eligibility is lost.
- Standardize the current residual using rolling training-window residual mean and sample standard deviation. Enter when z-score crosses +entry threshold (short spread) or -entry threshold (long spread). Exit when absolute z-score is at or below the configured exit threshold; optionally force close at fold/run end.
- Generate a signal after a bar closes and simulate its fill only at the next bar's open. No lookahead.
- Model book capacity as `bar_volume * participation_rate` for each leg. If either leg cannot fill its full requested quantity, scale both legs to the lower fill ratio (partial pair fill); if capacity is zero/missing, leave both legs unfilled. Track cash, units, fees and marked-to-market pair equity consistently.
- Validate configuration ranges server-side. Pair symbols must be distinct; lookback must allow enough observations for regression/test; `0 <= exit_z < entry_z`; p-value threshold in `(0, 1)`; positive volume participation no greater than a conservative cap.
- Walk-forward folds partition available data chronologically, with a configurable minimum training segment and non-overlapping held-out segments. Fold-local estimator state resets for each fold. Include no fold result when test segment has no usable data and report the reason.

## API and data contract

Extend `BacktestRequest` to accept `kind="pairs"`, `symbol_b`, and a nested/configurable `pairs` object with `lookback`, `entry_z`, `exit_z`, `cointegration_pvalue`, `walk_forward_folds`, `spread_floor_bps`, `range_factor`, and `participation_rate`. Keep current baseline and LLM request behavior backward compatible. Validate at request boundary and again in the service layer.

Store pair runs in existing `agentic_lab` records with:

- `kind: "pairs"`, readable pair label and `symbol`/`symbol_b`.
- `pair_config` and an execution-model label/parameters.
- `pair_series`: bounded/downsampled timestamp, spread, z-score, beta and cointegration fields for charting and training context.
- Per-leg trade/fill records, preserving side, entry/exit, quantity, fill status, costs and pair P&L.
- `walk_forward`: fold boundaries, p-values, sample counts, and out-of-sample metrics, plus aggregated out-of-sample metrics where mathematically meaningful.
- Overall performance metrics and an explicit warning that synthetic order-book fills are not L2 replay.

The existing run/list/job endpoints remain the interface; the shared UI launcher submits through `/agentic-lab/backtest`, polls the existing job path, and refreshes run history.

## UI

- Add a shared component for pair-run parameters/status, mount it in Agentic Lab and Backtester.
- For usability, present pair selection, signal parameters, walk-forward count, and synthetic-book assumptions with explanatory text and safe defaults.
- Backtester displays pair identity, OOS fold summary, cointegration/z-score series (with threshold reference lines), pair fills/trades, and synthetic book methodology/capacity in the selected run detail. Existing single-symbol result rendering remains intact.
- Display unavailable/insufficient-data cases as explicit errors or empty-state explanations, never as apparently valid zero-return runs.

## Dependencies and risks

- `statsmodels` is not currently a declared dependency. Add a pinned compatible version to both backend deployment and root requirements only after verifying current Python/SciPy constraints. Use `statsmodels.tsa.stattools.coint` (Engle–Granger; null hypothesis is no cointegration), but make the statistical meaning clear in UI/docs. If dependency footprint or version compatibility is unsuitable, stop and revise the design rather than substituting an undocumented test.
- Historical volume may be missing/zero for some providers/instruments. Do not fabricate capacity; report no fill / missing volume.
- OHLCV cannot reconstruct historical order-book queues, spread or intrabar path. Treat the synthetic model only as a deterministic stress approximation.
- Per-symbol provider fetch and timestamp alignment can produce unequal histories; pair-run tests must cover stale/missing timestamps and timezone normalization.
- The existing run storage is a capped local JSON store. This increment does not change persistence semantics; records must remain serializable and bounded.

## Tests and acceptance criteria

- Unit tests: OLS beta/intercept, Engle–Granger gate on cointegrated vs independent series, no lookahead in beta/z-score, crossed entry/exit thresholds, pair-leg direction, alignment, missing/zero volumes, partial paired capacity, costs, fold chronology and state reset.
- Service tests: fetch two symbols; fail clearly for identical symbols or insufficient common bars; store serializable pair runs with OOS outputs and synthetic-book caveat.
- API tests: valid pairs request creates/polls a job; malformed thresholds/symbol pair/fold counts produce HTTP 422/400; baseline/LLM API behavior remains backward compatible.
- Frontend typecheck/build and component/UI verification: launch form available in Agentic Lab and Backtester; new run appears in saved history with pair series, fills, synthetic caveat and walk-forward data; existing run selection still works.
- No claims that the strategy optimizes returns, that cointegration guarantees convergence, or that walk-forward eliminates overfitting.
