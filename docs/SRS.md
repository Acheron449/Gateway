# Gateway — Software Requirements Specification

| Field | Value |
| --- | --- |
| Document | `docs/SRS.md` — single source of truth |
| Version | 1.0 |
| Date | 2026-11-07 |
| Status | Approved scope. P1 (build + hosting rescue) and P2 (identity + isolation model) implemented 2026-11-07; P3–P6 not started |
| Supersedes | `phase-0..9-plan.md`, `phase-5-prerequisites.md`, `phase-8-draft.md`, `gateway-roadmap.md`, `auth0.md`, `status.md` (all moved to [`archive/`](archive/)) |
| Related, still current | [`deployment.md`](deployment.md) (hosting runbook), [`superpowers/specs/`](superpowers/specs/) (security remediation designs) |

This document defines what Gateway v1 **is**, what it must do, and what it must not do. Requirements are numbered and testable. Where a requirement describes work already in the tree, it says so; where it describes new work, it says that too.

---

## 1. Purpose and scope

### 1.1 Product statement

Gateway is a **backtesting and demo-trading workspace for algorithmic strategies and trading bots**. A user defines a strategy, runs it against historical market data, sees cost-aware results, then runs it as a bot against a simulated account — with no connection to a brokerage, a bank, or real capital anywhere in the system.

The site exists to answer one question honestly: *would this rule set have made or lost money, after realistic costs, and how much of that result is luck?* Two quantitative modules answer the follow-up questions:

- **Monte Carlo** quantifies how much of a result could be noise, and what the risk profile looks like across thousands of alternate histories.
- **Black-Scholes** gives options a defensible theoretical fair value, so a strategy trading options can be judged against a model rather than a vibe.

A third module, the **simulated order book**, visualises the hypothetical participants behind a price chart as a horizontal histogram — explicitly labelled as a simulation, never presented as exchange data.

### 1.2 What this system is not

| Not this | Consequence |
| --- | --- |
| A broker or order router | No broker API is contacted, ever. No order-placement code path exists in v1. |
| A live trading platform | `GATEWAY_EXECUTION_MODE` is fixed at `paper`. There is no `live` mode to enable. |
| A market data redistributor | Data is fetched for the signed-in user's own analysis under each provider's terms. |
| Investment advice | Every result view carries the model/assumption disclaimer in §6.6. |
| A real-time market data terminal | Quotes and history are delayed public data; freshness is always displayed. |

### 1.3 Definitions

| Term | Meaning |
| --- | --- |
| **Strategy** | An immutable, content-addressed specification of entry/exit/sizing/invalidation rules (§4.4). |
| **Backtest** | A deterministic replay of a strategy over historical bars, producing a run receipt. |
| **Demo trade** | A simulated order filled by the internal simulator against modelled prices and costs. Never a broker fill. |
| **Bot** | A running process that evaluates a strategy on a schedule over historical or delayed data and writes demo trades. A bot is not a live-trading process. |
| **Run receipt** | The immutable record of everything needed to reproduce a backtest: data hash, window, costs, engine version, seed. |
| **Simulated ladder** | The synthetic order book produced by §5.3. Not exchange L2 data. |
| **Provenance** | `source`, `fetched_at`, `data_time`, `coverage`, `delay_seconds`, `entitlement` attached to every market record. |

---

## 2. Users and use cases

| Persona | Need |
| --- | --- |
| **Researcher** (primary) | Test a rule set quickly, see whether it survives costs, and know whether the result is reproducible. |
| **Bot author** | Run a strategy as an automated process against a demo account and inspect its decisions. |
| **Reviewer / self-auditor** | Trace any result back to its data, assumptions and engine version. |

| ID | Use case | Success |
| --- | --- | --- |
| UC-1 | Build a strategy from a template or a specification form, save it, version it. | Strategy stored with a content hash; new edits create a new version. |
| UC-2 | Backtest a strategy over a chosen window and symbol. | Equity curve, metrics, trade list and run receipt returned; identical on re-run. |
| UC-3 | Run a strategy as a bot against a demo account. | Bot starts, writes demo trades, can be stopped, and its log is inspectable. |
| UC-4 | Stress a result with Monte Carlo. | Fan chart, VaR/CVaR, drawdown distribution, P(ruin), sizing suggestion — all seeded and reproducible. |
| UC-5 | Value an options position theoretically. | Fair value, greeks and implied vol for given inputs, with model boundaries stated. |
| UC-6 | See the participants behind a price level. | Horizontal histogram of simulated bid/ask size by archetype, labelled simulated, with its derivation shown. |

---

## 3. System overview and architecture

### 3.1 Components

| Component | Tech | Location |
| --- | --- | --- |
| SPA | React 18 + Vite 6 + TypeScript | `quant-app-v1/frontend` |
| API | FastAPI + pandas/statsmodels | `quant-app-v1/backend` |
| Auth + Postgres | Supabase (GoTrue + RLS) | hosted |
| Static hosting | **Cloudflare Workers static assets** (Pages-compatible) | `app.<domain>` |
| API hosting | Container behind Cloudflare proxy | `api.<domain>` |

### 3.2 Deployment topology (normative)

Cloudflare serves **static assets only** and cannot execute Python. The deployment is therefore:

```
browser ──► Cloudflare static assets (SPA, SPA-fallback 200 → index.html)
   │
   └─────► api.<domain> (Cloudflare proxy) ──► FastAPI container
                                                  │
                                                  └──► Supabase (Auth + Postgres)
```

| ID | Requirement |
| --- | --- |
| AR-1 | Cloudflare builds from the repository root: root `wrangler.jsonc` runs `npm run build` and uploads root `dist`; Pages can also build at the root or at `quant-app-v1/frontend`. The root and frontend paths produce `dist/index.html` and `dist/_redirects` without installing Python dependencies. |
| AR-2 | Cloudflare static-asset serving performs SPA fallback: unknown paths return `index.html` with HTTP 200. |
| AR-3 | `VITE_API_BASE` is set to the API origin **at build time** for every non-localhost environment. It is the only deployment-specific frontend configuration. |
| AR-4 | No Vercel artifacts remain: root `vercel.json`, `quant-app-v1/frontend/vercel.json`, `.vercelignore`, `.vercel/`. |
| AR-5 | The API is a single container image, not a serverless Python bundle, and has no function-size ceiling. |
| AR-6 | The API sets CORS to an explicit origin allowlist (the deployed frontend origin and localhost dev only); wildcard origins are rejected. |
| AR-7 | WebSocket upgrades reach the API host directly; they are not proxied through Cloudflare static assets. |

### 3.3 Environments

| Env | Frontend | API | Data |
| --- | --- | --- | --- |
| `local` | Vite dev `:5173` | uvicorn `:8000` | local SQLite |
| `preview` | Workers preview version (or Pages preview) | preview container | Supabase (preview project) |
| `production` | Workers production (or Pages) | production container | Supabase (production project) |
| `test` | build only | pytest | ephemeral SQLite |

`GATEWAY_EXECUTION_MODE=paper` is required in all four. Startup fails if it is set to anything else.

### 3.4 Build and bundle budgets

Measured on 2026-11-07 in `quant-app-v1/frontend`: `tsc --noEmit` exit 0; `npm run build` 176 modules, **6.4 s**, 1.01 MB JS (287 KB gzip), 157 KB CSS.

| ID | Requirement |
| --- | --- |
| AR-8 | The Cloudflare build completes in ≤ 2 minutes on the smallest available builder. |
| AR-9 | Total built JS after gzip stays ≤ 5 MB; if a single chunk exceeds 500 KB, it is split — the warning is not suppressed. |
| AR-10 | The API container image is ≤ 600 MB and builds in ≤ 10 minutes; the 405 MB model weights and 36 MB vendored tree are **not** in the build context. |
| AR-11 | Repository payload (clone) is ≤ 200 MB. |

### 3.5 Configuration

| Variable | Side | Purpose |
| --- | --- | --- |
| `VITE_API_BASE` | frontend build | API origin |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` | frontend build | Supabase client (public by design) |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | API | token verification, server-side writes |
| `JWT_SECRET_KEY` | API | session signing (local auth fallback in dev only) |
| `GATEWAY_EXECUTION_MODE` | API | must be `paper` |
| `GATEWAY_DATA_DIR` | API | writable path for local SQLite/job scratch |
| `GATEWAY_OPERATOR_IDS` | API | comma-separated user ids allowed to perform global actions; empty ⇒ deny |

---

## 4. Functional requirements

Status legend: **[exists]** already in tree · **[extend]** modify existing · **[new]** to build.

### 4.1 Accounts and sessions

| ID | Requirement | Status |
| --- | --- | --- |
| FR-A1 | Sign-up and sign-in are handled by Supabase Auth (`signInWithPassword`, `signUp`) from the SPA. | [exists] |
| FR-A2 | The API verifies a Supabase access token by introspection and derives the principal id from it; no client-supplied user id is ever trusted. | [exists] |
| FR-A3 | Sign-out clears the app session **and** all user-namespaced browser state (chat/session caches keyed by user). | [extend] |
| FR-A4 | Every private row is scoped to the verified principal; unauthenticated access to a private route returns 401, cross-user access returns 404 (not 403). | [new] |
| FR-A5 | `GET /auth/me` returns the principal's id, email and display name. | [exists] |
| FR-A6 | **Auth0 is removed.** No Auth0 library, component, bridge, env var, or RS256 verification path remains. | [new] |
| FR-A7 | Local email/password remains available **only** when `GATEWAY_ENV=local`, for tests and offline development. | [extend] |

### 4.2 Market data

| ID | Requirement | Status |
| --- | --- | --- |
| FR-D1 | One default historical source: Yahoo Finance via `yfinance` (keyless). Crypto may fall back to CCXT. No multi-provider fallback chain. | [extend] |
| FR-D2 | `GET /history/{symbol}?interval=&range=` returns OHLCV with provenance on every bar. | [exists] |
| FR-D3 | `GET /quotes?symbols=` returns batch quotes with a 45 s merge cache and per-symbol freshness. | [exists] |
| FR-D4 | `GET /catalogue` and `GET /catalogue/search` serve the versioned US-equity catalogue. | [exists] |
| FR-D5 | When a source is unavailable the response says unavailable with a reason; partial or substituted data is never returned. | [extend] |
| FR-D6 | Bars are bounded: ≤ 20 000 rows per request, ≤ 5 000 per symbol in a backtest. Over-limit requests are rejected with 400. | [new] |
| FR-D7 | Every response carries `data_time` ≤ `fetched_at`; the UI shows the delay. | [exists] |

### 4.3 Chart workspace

| ID | Requirement | Status |
| --- | --- | --- |
| FR-W1 | The workspace renders candlesticks with timeframe selection and volume. | [exists] |
| FR-W2 | Overlays: SMA/EMA, RSI, Bollinger bands. Each is toggleable and persisted per user. | [exists] |
| FR-W3 | Pattern detection (head-and-shoulders, pivots) is a display overlay only; it never places an order. | [exists] |
| FR-W4 | The right-hand inspector shows price, change, freshness badge, and the active strategy's latest backtest summary. | [extend] |
| FR-W5 | Empty, loading and error states exist for every panel; no raw JSON is ever rendered. | [extend] |

### 4.4 Strategy definition

| ID | Requirement | Status |
| --- | --- | --- |
| FR-S1 | A strategy is a typed spec: `asset_universe`, `timeframe`, entry rule, exit rule, sizing rule, invalidation rule, cost assumptions. | [exists] |
| FR-S2 | The spec is content-addressed; any edit produces a new version, and the prior version is immutable. | [exists] |
| FR-S3 | Version allocation is atomic (`BEGIN IMMEDIATE`) and stores `content_hash` in a nullable column. | [exists] |
| FR-S4 | A strategy can be created from a **template** (SMA cross, RSI mean-reversion, cointegration pair) without an LLM. | [new] |
| FR-S5 | Generated or pasted specs require explicit user approval before a run; the normalized rules are shown as text. | [extend] |

### 4.5 Backtesting

| ID | Requirement | Status |
| --- | --- | --- |
| FR-B1 | Deterministic replay: identical inputs (data hash, spec hash, engine version, seed) produce byte-identical metrics. | [extend] |
| FR-B2 | Costs are modelled explicitly: commission per trade, half-spread, slippage in basis points, and an optional latency-bar. | [extend] |
| FR-B3 | Long and short positions; no leverage above a configured cap; no shorting where the instrument disallows it. | [extend] |
| FR-B4 | Outputs: equity curve, trade list, hit rate, profit factor, expectancy, max drawdown, Sharpe/Sortino, exposure, turnover. | [exists] |
| FR-B5 | Every run stores a **receipt**: data hash, window, timeframe, cost assumptions, engine version, seed, timestamp. | [new] |
| FR-B6 | In-sample / out-of-sample split is required: any run reports OOS metrics separately, or states OOS was not evaluated. | [new] |
| FR-B7 | A run is reproducible from its receipt alone via `POST /backtest/run` with the stored parameters. | [new] |
| FR-B8 | Runs are owner-scoped and capped (≤ 50 retained per user, oldest pruned). | [extend] |

### 4.6 Demo trading simulator

| ID | Requirement | Status |
| --- | --- | --- |
| FR-T1 | A demo account has cash, positions, open orders, fills and an equity history. All values are simulated. | [exists] |
| FR-T2 | Order admission is a single shared path: risk checks (buying power, concentration, max daily loss, kill switch) run **before** any order is persisted. | [extend] |
| FR-T3 | Accepted orders reserve buying power atomically; fills re-validate constraints and release the reservation. | [extend] |
| FR-T4 | Fill simulation uses the configured cost model, never a broker. | [exists] |
| FR-T5 | A durable kill switch blocks new admissions and is the single authoritative state read by both the UI and the engine. | [extend] |
| FR-T6 | Every demo order and fill is labelled `simulated` in the API payload and in the UI. | [exists] |
| FR-T7 | No code path constructs a request to a broker host. Enforced by a static test that scans imports. | [new] |

### 4.7 Bot runner

| ID | Requirement | Status |
| --- | --- | --- |
| FR-R1 | A bot binds a strategy version to an instrument, timeframe and demo account, and runs on a schedule (minimum 60 s). | [new] |
| FR-R2 | `POST /bots/runs` starts a run; `GET /bots/runs` lists; `POST /bots/runs/{id}/stop` stops; `GET /bots/runs/{id}/log` returns decisions. | [new] |
| FR-R3 | Every bot decision is logged with inputs, computed signal, risk verdict and action taken. | [new] |
| FR-R4 | Bots operate on delayed/historical data only. A bot cannot be configured against a live feed. | [new] |
| FR-R5 | Concurrent runs per user ≤ 2; each run is bounded in duration and iterations. | [new] |
| FR-R6 | A bot writes only through the §4.6 admission path — it holds no privileged write access. | [new] |

### 4.8 Monte Carlo risk

| ID | Requirement | Status |
| --- | --- | --- |
| FR-M1 | `POST /quant/monte-carlo` accepts a strategy run id **or** an explicit return series, plus seed, path count, method. | [new] |
| FR-M2 | Methods: `gbm` and `bootstrap` (§5.1). | [new] |
| FR-M3 | Outputs: percentile fan (5/25/50/75/95), terminal distribution, VaR/CVaR at 95 and 99, max-drawdown distribution, P(ruin), median time-to-ruin. | [new] |
| FR-M4 | The response echoes seed, path count, method, data hash and engine version; re-running with the same values yields identical numbers. | [new] |
| FR-M5 | Default 10 000 paths, hard cap 50 000, runtime ≤ 5 s at default. | [new] |
| FR-M6 | The UI renders the fan and the drawdown histogram, and labels the output as a simulation of the strategy's own past, not a forecast. | [new] |
| FR-M7 | Sizing suggestion: position size such that simulated CVaR at 99 stays within a user-set risk budget. | [new] |

### 4.9 Options fair value (Black-Scholes)

| ID | Requirement | Status |
| --- | --- | --- |
| FR-O1 | `POST /quant/options/price` takes `S, K, T, r, q, sigma, type` and returns fair value plus full greeks (§5.2). | [new] |
| FR-O2 | `POST /quant/options/implied-vol` takes a market price and returns implied volatility with an explicit convergence status. | [new] |
| FR-O3 | Invalid inputs (T ≤ 0, σ < 0, S ≤ 0, K ≤ 0) return 400 with the offending field named, never NaN or Infinity. | [new] |
| FR-O4 | The API declares model boundaries in its response metadata: European exercise, no early exercise, continuous dividend yield, constant volatility, frictionless markets. | [new] |
| FR-O5 | The UI shows fair value against a user-entered market price and the difference in both currency and implied-vol terms. | [new] |
| FR-O6 | No options chain or market-options data feed is required; the module is a calculator over user/strategy-supplied inputs. | [new] |

### 4.10 Simulated order book

| ID | Requirement | Status |
| --- | --- | --- |
| FR-L1 | `POST /quant/orderbook/simulate` returns a bid/ask ladder with per-level size and per-archetype attribution (§5.3). | [new] |
| FR-L2 | The UI renders it as a **horizontal histogram**: price on the vertical axis, size extending horizontally, bids and asks mirrored around the mid. | [new] |
| FR-L3 | Each level expands to show its derivation (archetype contributions, agent counts, parameters, seed). | [new] |
| FR-L4 | The surface is labelled "Simulated liquidity — not exchange data" in the UI and in the API payload (`simulated: true`). | [new] |
| FR-L5 | The simulation uses the same seed discipline as §4.8; identical seed and inputs yield an identical ladder. | [new] |
| FR-L6 | Output size is bounded: ≤ 200 price levels per side, ≤ 50 archetype segments per level. | [new] |

### 4.11 Results and reporting

| ID | Requirement | Status |
| --- | --- | --- |
| FR-P1 | A run report shows equity curve, drawdown chart, metrics table, trade list and receipt. | [exists] |
| FR-P2 | Two runs can be compared side by side (same instrument, different versions or parameters). | [extend] |
| FR-P3 | Every displayed number is traceable to its run receipt in ≤ 2 clicks. | [new] |
| FR-P4 | Reports are downloadable as CSV; the CSV is generated server-side with formula-injection escaping. | [new] |

---

## 5. Quantitative specifications

These sections are normative. Implementations must match the stated formulas and expose the stated parameters; deviations require a version bump and a document amendment.

### 5.1 Monte Carlo

**Inputs.** Starting equity `E0`, per-bar returns or an equity curve, horizon `H` bars, path count `N`, seed `s`, method `m ∈ {gbm, bootstrap}`, ruin threshold `R` (default 50% of `E0`).

**Method `gbm`.** Fit `μ` and `σ` from the input log-returns (`μ` annualised then per-bar; `σ` per-bar sample standard deviation). For each path and each step:

```
r_t   = (μ − σ²/2)·Δt + σ·√Δt·Z_t        Z_t ~ N(0,1)
S_t+1 = S_t · exp(r_t)
```

RNG: PCG64 seeded with `s`; the same `(s, N, H)` must yield the same paths across platforms and versions.

**Method `bootstrap` (default for strategy runs).** Stationary block bootstrap of the observed log-returns with expected block length `L` (default 20 bars), preserving fat tails, volatility clustering and short-range autocorrelation. Block starts drawn uniformly; wrap-around permitted.

**Outputs.**

| Output | Definition |
| --- | --- |
| Percentile fan | 5/25/50/75/95 quantiles of `S_t` at each `t` |
| Terminal distribution | Histogram of `S_H` (≤ 60 bins) |
| `VaR_α` | `−quantile_{1−α}(terminal P&L)` for α ∈ {0.95, 0.99}, reported as a positive loss |
| `CVaR_α` | Mean loss conditional on exceeding `VaR_α` |
| Max drawdown | Per path, then its distribution (p50/p95/p99 and worst) |
| `P(ruin)` | Fraction of paths whose equity ≤ `R` at any point |
| Median time-to-ruin | Median first-crossing bar among ruined paths |

**Sizing (FR-M7).** Recommend the largest position multiplier `k ∈ (0, 3]` such that `k · CVaR_99 ≤ risk_budget`, floored to 0.05 increments; if no `k` satisfies the budget, recommend 0 and say so.

**Reproducibility.** The response includes `{seed, paths, horizon, method, block_length, data_hash, engine_version}`. Two calls with identical values produce identical arrays.

**Validation (must be tested).**

1. Zero-volatility input collapses every path to the deterministic curve.
2. With `N = 50 000` and known `μ, σ`, the simulated terminal mean and standard deviation fall within 1% / 2% of analytic values.
3. `VaR_99 ≥ VaR_95` and `CVaR_α ≥ VaR_α` for every α.
4. Seed determinism: same seed twice ⇒ identical output hash; different seeds ⇒ different hash.
5. `P(ruin) = 0` when `R = 0`, and `P(ruin) = 1` when `R ≥ E0`.

### 5.2 Black-Scholes

Continuous dividend yield `q`, continuously compounded risk-free rate `r`, time to expiry `T` in years, volatility `σ`.

```
d1 = ( ln(S/K) + (r − q + σ²/2)·T ) / ( σ·√T )
d2 = d1 − σ·√T
C  = S·e^(−qT)·N(d1) − K·e^(−rT)·N(d2)
P  = K·e^(−rT)·N(−d2) − S·e^(−qT)·N(−d1)
```

Greeks (call unless noted; `n(·)` is the standard normal PDF):

| Greek | Call | Put |
| --- | --- | --- |
| Delta | `e^(−qT)·N(d1)` | `−e^(−qT)·N(−d1)` |
| Gamma | `e^(−qT)·n(d1) / (S·σ·√T)` | same |
| Vega | `S·e^(−qT)·n(d1)·√T` | same |
| Theta | `−S·e^(−qT)·n(d1)·σ/(2√T) + q·S·e^(−qT)·N(d1) − r·K·e^(−rT)·N(d2)` | `−S·e^(−qT)·n(d1)·σ/(2√T) − q·S·e^(−qT)·N(−d1) + r·K·e^(−rT)·N(−d2)` |
| Rho | `K·T·e^(−rT)·N(d2)` | `−K·T·e^(−rT)·N(−d2)` |

Reporting conventions: Theta per **calendar day** (`/365`), Vega and Rho per **1%** change (scale by 0.01), so a UI showing "Vega 12.4" means 12.4 currency units per volatility point.

**Implied volatility.**

- Solve `BS(σ) = market_price` on `σ ∈ [1e-4, 5.0]`.
- Primary: Brent's method; fallback: bisection. Tolerance `1e-8` on σ or `1e-6` on price; max 200 iterations.
- Reject before solving when price `< max(0, intrinsic)` (below `S·e^(−qT) − K·e^(−rT}` for calls) or above `S·e^(−qT)` for calls / `K·e^(−rT)` for puts — return 422 with the violated bound, never a silent clamp.
- Return `converged: bool` and iteration count.

**Model boundaries (must be returned with every response — FR-O4).** European exercise only; no early exercise or American premium; continuous dividend yield, not discrete dividends; constant σ (no smile); constant r; frictionless, continuous trading; no credit, funding or margin effects. Options with < 1 day to expiry are flagged as numerically unstable.

**Validation.**

1. Put-call parity: `C − P = S·e^(−qT) − K·e^(−rT)` within `1e-8`.
2. Monotonicity: call value increases in `S` and `σ`, decreases in `K`; delta bounds `[0,1]` and `[−1,0]`.
3. Round-trip: `IV(BS(σ)) = σ` within `1e-6` across a grid of `S/K ∈ [0.5, 1.5]`, `T ∈ [1/365, 3]`, `σ ∈ [0.05, 2]`.
4. Deep out-of-the-money and near-expiry cases return finite values or an explicit error — never NaN, Infinity, or a negative price.
5. Greeks match central finite differences within `1e-4` relative.

### 5.3 Simulated order book

**Purpose.** Show *who* could plausibly be behind a price level, as a visual companion to the chart. It is a model output, not a feed.

**Agent population.** For each simulation, instantiate `A` agents (default 500) across four archetypes with configurable weights (defaults in brackets):

| Archetype [weight] | Behaviour |
| --- | --- |
| Market maker [0.40] | Quotes symmetric size around the mid with a spread drawn from `N(spread_base, spread_cv)`, skewed against its own inventory (inventory penalty linear in signed position). |
| Momentum [0.20] | Quotes on the side of the recent return; size proportional to `min(|z(return)|, 3)` over the lookback. |
| Noise [0.30] | Random side, size lognormal, price within ±`band` of mid (default 0.5%). |
| Large passive [0.10] | Block liquidity at distance ≥ 0.5% from mid, size drawn from the top decile of the size distribution. |

**Construction.** For each step (default 1, since the target is a snapshot):

1. Draw `mid` and recent return from the referenced bar (or from user-supplied price context).
2. Each agent emits `(price, size, side)` per the archetype rule; prices snap to a tick grid (default 0.01).
3. Aggregate into price bins; per bin, sum size **by archetype** and store the contribution vector.
4. Emit bids below mid, asks above mid; cap at 200 levels per side.

**Response shape.**

```json
{
  "simulated": true,
  "mid": 191.42, "seed": 7, "agents": 500,
  "levels": [
    {"price": 191.40, "side": "bid", "size": 18400,
     "contributions": [{"archetype": "market_maker", "size": 11000},
                       {"archetype": "noise", "size": 5400},
                       {"archetype": "large_passive", "size": 2000}]}
  ],
  "parameters": {"spread_base": 0.0004, "band": 0.005, "inventory_penalty": 0.15},
  "engine_version": "ob-1.0.0"
}
```

**Rendering (FR-L2).** Horizontal histogram: price descending on the Y axis with the mid drawn as a reference line, bid size extending left and ask size extending right from that axis. Bars are stacked by archetype with a stable colour per archetype and a legend. Hovering a level shows absolute size, share of side, and the derivation breakdown. The label "Simulated liquidity — not exchange data" is permanently visible on the panel, not only in a tooltip.

**Validation.**

1. Determinism by seed (FR-L5).
2. Conservation: total simulated size equals the sum of agent sizes emitted (no size invented during aggregation).
3. Market-maker share decreases as inventory grows in magnitude.
4. The ladder is always non-crossed: best bid < best ask.
5. Bounds honoured (FR-L6) for adversarial inputs.

---

## 6. Non-functional requirements

### 6.1 Performance and capacity

| ID | Requirement |
| --- | --- |
| NFR-1 | API p95 ≤ 1.5 s for 2 years of daily bars; ≤ 300 ms for `/catalogue/search`. |
| NFR-2 | A 2-year daily single-instrument backtest completes in ≤ 10 s. |
| NFR-3 | Monte Carlo at 10 000 paths completes in ≤ 5 s; order-book simulation in ≤ 1 s. |
| NFR-4 | Cold API start ≤ 15 s (container, warm filesystem). |
| NFR-5 | Designed for ≤ 50 concurrent users; the demo simulator is not built for high-frequency concurrency. |

### 6.2 Security baseline

Carried forward from the 2026-10-18 remediation designs ([`superpowers/specs/`](superpowers/specs/)); every item is an acceptance gate, not a nice-to-have.

| ID | Requirement |
| --- | --- |
| NFR-6 | Ownership derives from the verified principal only. No `user_id` is read from request bodies, query strings or headers. |
| NFR-7 | Private reads/writes are scoped to the principal; cross-user access is indistinguishable from not-found. |
| NFR-8 | Global actions (shared config, global kill switch) require membership of `GATEWAY_OPERATOR_IDS` and **fail closed** when the list is empty. |
| NFR-9 | Security headers on every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, restrictive `Permissions-Policy`, and a CSP without `unsafe-eval` in the production build. |
| NFR-10 | Rate limiting: 240/min and 3000/hour per IP by default; authentication endpoints stricter. |
| NFR-11 | Error responses expose a fixed message and a status code; upstream exception text (which may embed credentials or URLs) is never returned. |
| NFR-12 | All collection-shaped inputs are bounded before allocation: candle arrays, symbol lists, path counts, level counts, uploaded text. |
| NFR-13 | No runtime code installation. The Kronos installer route is removed with Kronos; no endpoint may shell out to mutate the environment. |
| NFR-14 | Secrets live only in the API environment or an encrypted store; none is readable from the browser bundle. Provider keys are never cached client-side. |
| NFR-15 | Markdown/HTML rendering uses a linear tokenizer with an aggregate response cap; no unbounded regex over user text. |
| NFR-16 | Dependency audit: zero critical/high advisories at launch; `bandit` (or equivalent) clean on `app/`. |

### 6.3 Data integrity

| ID | Requirement |
| --- | --- |
| NFR-17 | Simulated fills, backtest outputs and (never present) broker facts are distinct stores; no code assumes they are interchangeable. |
| NFR-18 | Every run receipt is immutable once written. |
| NFR-19 | Legacy rows with no recorded owner remain inaccessible through user routes until an explicit, reviewed migration assigns them. They are never auto-assigned to the first user to log in. |

### 6.4 Observability

| ID | Requirement |
| --- | --- |
| NFR-20 | `GET /health` reports environment, execution mode and per-capability availability without secrets. |
| NFR-21 | Structured request logging with a request id, duration and status; no tokens, keys or PII in logs. |
| NFR-22 | Error aggregation is optional and off by default; when enabled it must scrub tokens and email addresses. |

### 6.5 Accessibility and UX

| ID | Requirement |
| --- | --- |
| NFR-23 | Keyboard reachable: every primary action, including the command palette (⌘K). |
| NFR-24 | Colour is never the sole carrier of meaning (direction, risk, simulation label each have text or shape). |
| NFR-25 | The layout collapses to a usable single column at ≤ 1024 px. |
| NFR-26 | Contrast ≥ 4.5:1 for body text; focus rings visible on the dark canvas. |

### 6.6 Legal and disclaimers

| ID | Requirement |
| --- | --- |
| NFR-27 | A persistent notice states: results are simulated, historical, and not investment advice. |
| NFR-28 | Backtest, Monte Carlo and order-book surfaces each carry their own scope line (past performance / simulation / not exchange data). |
| NFR-29 | The site records acceptance of the notice per user on first use. |
| NFR-30 | No claim of accuracy, profitability or "live" capability appears anywhere in the UI or metadata. |

---

## 7. Data model and ownership

### 7.1 Tables (Supabase Postgres)

| Table | Key columns | Owner-scoped |
| --- | --- | --- |
| `profiles` | `id` (= `auth.users.id`), `email`, `display_name`, `created_at` | self |
| `preferences` | `user_id`, `theme`, `watchlists jsonb`, `saved_layouts jsonb` | yes |
| `notice_acceptances` | `user_id`, `version`, `accepted_at` | yes |
| `strategies` | `id`, `owner_id`, `name`, `created_at` | yes |
| `strategy_versions` | `strategy_id`, `version`, `spec jsonb`, `content_hash`, `created_at` | via strategy |
| `backtest_runs` | `id`, `owner_id`, `strategy_version_id`, `receipt jsonb`, `metrics jsonb`, `created_at` | yes |
| `portfolios` | `id`, `owner_id`, `cash`, `base_currency` | yes |
| `orders` | `id`, `portfolio_id`, `symbol`, `side`, `qty`, `type`, `status`, `simulated` | via portfolio |
| `fills` | `id`, `order_id`, `price`, `qty`, `costs jsonb`, `simulated` | via portfolio |
| `positions` | `portfolio_id`, `symbol`, `qty`, `avg_price` | via portfolio |
| `bot_runs` | `id`, `owner_id`, `strategy_version_id`, `status`, `started_at`, `stopped_at` | yes |
| `bot_logs` | `bot_run_id`, `bar_time`, `signal`, `risk_verdict`, `action` | via run |

### 7.2 RLS shape

| ID | Requirement |
| --- | --- |
| DR-1 | RLS is enabled on every table in §7.1 with no permissive `USING (true)` policy. |
| DR-2 | Read policy: `auth.uid() = owner_id` (or a join to the owning row for child tables). |
| DR-3 | Write policy: `auth.uid() = owner_id` for `INSERT`/`UPDATE`/`DELETE`; `owner_id` is immutable after insert. |
| DR-4 | The API uses the service role only for server-side jobs that have already authorised the principal; it never forwards a browser-supplied id. |
| DR-5 | Anonymous access to any table returns zero rows, verified by test. |

### 7.3 Legacy data

| ID | Requirement |
| --- | --- |
| DR-6 | Rows created before ownership existed are `owner_id IS NULL` and therefore invisible under DR-2. |
| DR-7 | A quarantine migration may assign them only with explicit user direction; it is not part of v1. |

---

## 8. Out of scope

Removed from the product, not merely deferred. Removing them is what makes the build fit its budget.

| Removed | Rationale |
| --- | --- |
| **Live broker execution** (Alpaca live, order placement, `/live` router, activation gates) | The product is a demo harness. No broker integration exists in v1. |
| **Phase 4/5 reconciliation evidence** (≥ 1 000 settled fills, < 0.1% discrepancy, independent comparator, durable order intent) | Gate only exists to protect live capital, which v1 does not touch. |
| **Auth0** — `lib/auth0.ts`, `Auth0Button.tsx`, `Auth0Bridge.tsx`, `context` branches, backend RS256 path, `AUTH0_*` / `VITE_AUTH0_*` | Supabase Auth is the only identity provider. No compatibility shim, no dormant code. |
| **Vercel** — root `vercel.json`, `frontend/vercel.json`, `.vercelignore`, `.vercel/` | Cloudflare cannot host Python; Vercel is no longer the provider. |
| **Kronos** — 405 MB of weights under `backend/models/`, installer route, forecast endpoint | Largest single cause of build failure; a probabilistic price forecast is not required to backtest rules. |
| **OpenBB** — context provider, context server, `/openbb/*` routes, AGPL review | Removed with the provider chain; the remaining modules, flags, routes and CLI were deleted on 2026-11-07. The retained history provider covers v1. |
| **Stripe, Resend** | No paid tier, no transactional email in v1. |
| **SEC filings** | Not needed to judge a rule set. |
| **News/calendar multi-provider chains** | One source or none; event-aware backtesting is deferred. |
| **Journal, vault, divergence scorecards, multi-portfolio/RBAC groups** | Collaboration and secrets storage are not part of the research loop. |
| **AI chat harness (11 LLM providers) and Agentic Lab (research/trading-log/LLM tabs)** | Deferred, **not deleted** — see §9 P7 note. The code stays in the tree behind a disabled navigation entry until P6 decides. |
| **Phase 7 SEO programme** (sitemap of 200 doc URLs, backlink strategy, Lighthouse ≥ 90 on served Markdown) | Replaced by NFR-9/27 and a five-line `robots.txt`/sitemap for the SPA. |
| **Phase 8/9 external-service layers** | No vendor beyond Supabase, Cloudflare and the data provider. |

---

## 9. Phases and gates

Each phase ends with an exit gate. A gate is pass/fail against the listed criteria; "mostly done" is a fail.

### P1 — Build and hosting rescue

**Status: complete except the API image measurement (2026-11-07).**

**Goal:** a Cloudflare deployment that builds in minutes and an API that deploys as a container.
**Depends on:** nothing.

Deliverables: Workers Builds config (`wrangler.jsonc`) and Pages project configured (AR-1..AR-3); delete Vercel artifacts (AR-4, §8); remove `backend/models/` and `backend/vendor/` from the repository and build context (AR-10, AR-11); `Dockerfile` producing the API image; CI runs the root and frontend builds for the SPA.

**Exit gate:** Cloudflare production build ≤ 2 min at ≤ 5 MB gzip; API image ≤ 600 MB and boots to `/health`; `git clone` ≤ 200 MB; zero Vercel files; no build step compiles Python.

**Record (2026-11-07):** Vercel artifacts deleted, the 5 255 committed `node_modules` files untracked, `public/_redirects` added, and the Dockerfile rebased on the `backend/` context with `models/` and `vendor/` excluded and the instrument catalogue copied. Root `wrangler.jsonc` targets the existing `gateway` Worker, runs `npm run build` during `wrangler deploy`/`versions upload`, and uploads root `dist`; a `wrangler versions upload --dry-run` passed from a clean output directory. The root `package.json` also supports Pages at either root, and the Python manifests live under `quant-app-v1/backend/requirements-full.txt` and `requirements-dev.txt`, so Cloudflare does not detect or install Python. The frontend build measured at ~1.2 s and 233 KB gzip; the API image size is **unmeasured** — `docker` is not installed on the development machine — so that clause stays open until CI or a local Docker run reports it.

### P2 — Identity and isolation

**Status: implemented (2026-11-07; strategy ownership closed 2026-11-08), except the live two-account run.**

**Goal:** Supabase Auth is the only sign-in; private data is isolated.
**Depends on:** P1.

Deliverables: FR-A1..A7 (Auth0 fully removed, FR-A6); §7 schema + RLS (DR-1..DR-7); tokens verified by introspection; namespaced client storage with sign-out clearing.

**Exit gate:** two-account test proves isolation on strategies, runs, orders and preferences; signed-out requests get 401; no Auth0 implementation remains (the guard test that asserts its absence is the only file that names it); no cross-user 403 leak.

**Record (2026-11-07):** Auth0 removed end to end — three frontend modules deleted, `@auth0/auth0-react` uninstalled (bundle 1 011 kB → 768 kB), the RS256/JWKS path, `warm_auth0_jwks`, `validate_auth_configuration` and every `AUTH0_*` variable deleted, and the 340-line `test_auth0.py` replaced by `test_auth_supabase_only.py` (16 passing). Local password tokens are confined to the local and test profiles. `supabase/schema.sql` carries the §7 owner-scoped tables with RLS enabled on all eleven and no permissive policy. Sign-out clears `gw_user_*` and the legacy user keys. **Not proven:** the two-account isolation run against a live Supabase project. The RLS model is reviewed in SQL, not yet exercised against a database, so the first gate clause stays open. **Resolved (2026-11-08):** `app/api/v1/strategies.py` now takes `CurrentUser` on all eight routes, stores `owner_id` on create, filters every read and write by principal, returns the same 404 for another account's strategy, version and deletion as for a missing id, and quarantines pre-ownership rows with a NULL owner (`tests/test_strategies_ownership.py`). `backtest.py` and `portfolio.py` were already principal-scoped, so no API module in the §7 owner set reads without one. Because the surface no longer depends on a shared store, `PrivateDataGateMiddleware` no longer answers 503 for `/strategies`. The live Supabase two-account run remains open.

### P3 — Market data and workspace

**Status: implemented (2026-11-07); both asset classes were exercised in the browser.**

**Goal:** a reliable chart with honest provenance.
**Depends on:** P2.

Deliverables: FR-D1..D7 (single provider, bounds); FR-W1..W5; catalogue retained.

**Exit gate:** charts render for a US equity and a crypto pair; unavailable-source path shows a reason, not substituted data; bar caps enforced; freshness visible on every quote.

**Record (2026-11-07):** `/history/{ticker}` no longer substitutes sources behind the caller's back. A named provider that cannot answer returns 503 `provider_unavailable` with the provider and the attempted list; Yahoo is the only default; CCXT is reachable for crypto pairs only, so an equity outage returns 502 `source_unavailable` instead of quietly serving exchange data. Bars are capped at 20,000 per request (previously a silent 2,000-row truncation) and refused with 400 `bar_limit` above it; backtests reject more than 5,000 bars per symbol. Provenance rides on every bar — `source`, `provider_version`, `fetched_at`, `data_time`, `entitlement`, and a `coverage` string that now reflects the asset class rather than always claiming US equities. The chart surfaces failures as a sentence with a Retry control instead of the raw response body, shows an empty state when a request succeeds with no bars, and the inspector carries a Live/Delayed/Stale freshness badge derived from the quote's own `data_time`. `tests/test_history_contract.py` covers the caps, source fidelity and per-bar provenance (42 passing across the contract, data-source and `as_of` suites); `tsc` and `vite build` are clean at 769 kB / 218 kB gzip. **In-browser check (2026-11-07, local stack):** AAPL rendered on a fresh Vite + uvicorn pair, and its inspector showed **STALE 8H** — the honest reading of a Friday close. BTC-USD rendered with **LIVE** at $75,826. Forcing the chart's provider to unconfigured Alpaca produced "No history data available for AAPL from Alpaca" with a Retry control and no substituted candles, which is the FR-D5 path working end to end. Live API checks alongside the UI: 455 bars for `tf=1h&limit=500` and a 400 `bar_limit` for `limit=20001`. The check also exposed three defects that are now fixed: the inspector's default quote source was Finnhub (unconfigured here), so every quote came back unavailable with no timestamp and the badge read "Freshness unknown" — the quote default is now Yahoo Finance, matching the single history default, and Yahoo quotes carry `data_time` from the latest 1m bar so the badge measures market data rather than fetch time; and selecting BTC-USD left "APPLE INC" in the inspector subtitle because the 404 from `/stocks/BTC-USD/metadata` retained the previous instrument, fixed by clearing identity on symbol change. **Fixed (2026-11-07):** the markets 1H chart's left-edge single-candle framing came from the empty first draw. `MainChart` stored a zero-width viewport before any bars arrived and kept it after the 300–455-bar series landed. The viewport is now created only after bars exist, zero-width/invalid views are discarded, short series keep the latest candle at the right edge, and polling follows the latest bar only when the user is already at the end. `e2e/markets-chart.spec.ts` pins 300 mocked hourly bars and asserts that the chart exposes 120 visible bars ending at the latest bar; the full Playwright suite is now 21 passing.

### P4 — Backtesting, demo trading, bots

**Status: implemented (2026-11-07): backend, API and the `/app/backtests` report screen.**

**Goal:** the core loop — define, test, run.
**Depends on:** P3.

Deliverables: FR-S1..S5; FR-B1..B8 (receipts, OOS, reproducibility); FR-T1..T7 (single admission path, kill switch, static broker-import test); FR-R1..R6 (bot runner); FR-P1..P4.

**Exit gate:** the same strategy re-run from its receipt produces identical metrics; a deliberate fee/slippage change moves results in the expected direction; a bot starts, logs decisions, stops, and cannot exceed the risk limits; the broker-import scan finds zero matches.

**Record (2026-11-07):** `POST /backtest/run` now executes a real deterministic backtest (`app/services/backtest_engine.py`, engine `bt-1.0.0`) over typed spec rules, with long/short entries, stop loss, explicit commission/half-spread/slippage/latency costs, and metrics for hit rate, profit factor, expectancy, max drawdown, Sharpe/Sortino, exposure and turnover. Every run stores a receipt carrying the spec, window, timeframe, bar count, costs, seed, engine version, timestamp and a SHA-256 `data_hash`; `POST /backtest/run` with `{"receipt": …}` recomputes from that receipt and returns **409 `data_changed`** with both hashes rather than quietly reporting different numbers. In-sample and out-of-sample metrics are always reported separately, and a run that disables the split says so (`oos.evaluated: false` with a reason). Runs are owner-scoped, capped at 50 per owner with oldest-first pruning, downloadable as server-generated CSV with formula-injection escaping, and comparable pairwise via `POST /backtest/compare`.

Demo trading has one admission path (`app/services/order_admission.py`) shared by the HTTP route and the bot runner: durable kill switch → risk checks → atomic cash reservation (`BEGIN IMMEDIATE` inside `insert_paper_order_reserved`) → persist. A rejected order never leaves a row behind, two orders cannot spend the same dollars, and a fill releases its reservation. The kill switch moved from a process flag to a SQLite row read on every check (`app/services/kill_switch.py`), so a restart or a second worker sees the same state and an unreadable store fails closed.

The bot runner (`app/services/bot_runner.py`, `/bots/runs…`) binds a strategy version to an instrument, timeframe and demo portfolio, ticks on a schedule of at least 60 s, refuses live feeds outright, allows at most two running bots per user, and bounds each run by iteration count and duration. Each decision is logged with the bar inputs, computed signal, risk verdict and resulting action, and every order it places goes through the shared admission path — it has no privileged write access.

The live-execution surface was deleted rather than disabled: `app/services/broker_service.py`, `app/services/alpaca_live.py`, `app/api/v1/live.py` and `app/trading_orchestrator.py` are gone, the `/journal/sync-live` route returns 410, AI routing accepts `paper` only, and the broker-import scan in `tests/test_p4_demo_trading.py` asserts zero trading-SDK imports and that those modules cannot reappear. 26 new tests cover the phase gate.

**Test status (2026-11-07):** the backend suite is green — **492 passed, 0 failed** (`PYTHONPATH=. python -m pytest -q -p no:warnings --ignore=vendor`), including the 31 §5.1 Monte Carlo, 34 §5.2 Black-Scholes and 42 §5.3 order-book tests recorded under P5 and the offline RLS schema contract in the ledger below. The five failures carried since P2/P3 were repaired, not skipped: the three key-store route tests now drive the route functions behind the middleware's auth and account-isolation gate (with a new transport test proving an authenticated provider write still stops at that gate), the WebSocket test drives both handshake handlers with a frame-level fake socket instead of the starlette/httpx-incompatible `TestClient`, and the catalogue test's fake `fetch_ohlcv` accepts the keyword-only `as_of` that `/stocks/{ticker}/metadata` forwards. The vendored Kronos harness needs matplotlib and is not part of the product, hence `--ignore=vendor`. The P6 hardening fixes added the seven `tests/test_security_hardening.py` regressions (environment-aware CSP, limiter middleware plus a functional 429, OpenBB absence) and extended the agentic-lab owner-scope test to require quarantined legacy runs. The NFR-6 fix adds `tests/test_portfolio_ownership.py` (per-user books and cross-owner 404s), and the NFR-15 cap is covered by `test_chat_stream_stops_at_aggregate_reply_cap` plus an HTTP SSE smoke test with the private-data gate bypassed. The live-provider runner `scripts/smoke_chat_stream.py` was added on 2026-11-07 but could not run: no provider key exists in any env file or the shell, so it exits 2 without contacting a provider; that is an environment gap, not a test failure. The stale `custom-openai` entry pointing at a dead localhost test port was removed from the provider store. The NFR-18 insert-only receipt guard is covered by `tests/test_p4_receipts.py::test_receipts_are_insert_only`. The NFR-21 request-logging tests are in `tests/test_observability.py`; the NFR-20 readiness/liveness tests are in `tests/test_health.py`; the NFR-22 error-aggregation tests are in `tests/test_error_aggregation.py`. The NFR-23..NFR-26 accessibility checks are Playwright tests in `e2e/accessibility.spec.ts` (3 passing); the full Playwright suite is 21 passing, including `e2e/strategy-studio.spec.ts` (2), the D4 legal checks in `e2e/legal.spec.ts` (2) and the moved report-screen launcher/Monte Carlo checks in `e2e/chat-proposal.spec.ts` (6). The NFR-29 Supabase RPC contract is covered by two tests in `tests/test_notice_acceptance.py`.

The report screen lives at `/app/backtests` ("Run reports" in the workspace rail, replacing the old redirect into Agentic Lab) and reads stored receipts: equity curve with the starting-capital line, drawdown from peak, a metrics table split full-window / in-sample / out-of-sample, the trade blotter, and the receipt — data hash, spec hash, seed, cost assumptions and strategy spec — one click from the summary. CSV export goes through the authenticated `/backtest/runs/{id}/csv`, and comparison mode diffs two runs' metrics and shows both receipts side by side. The same screen also hosts the LLM strategy launcher and the multi-run Monte Carlo comparison moved out of the retired Backtester panel. Because every receipt figure is rendered from the stored payload, a number on screen is always traceable to the run that produced it (FR-P3). **Exit-gate ledger (2026-11-07):** receipt replay reproduces identical metrics and a changed bar refuses replay with 409 `data_changed`; a fee/slippage change moves net P&L in the expected direction; a bot starts, logs decisions, stops at its iteration cap and cannot exceed its limits; the broker-import scan finds zero matches. FR-P3's traceability is now **one click** — the report screen's summary links straight to the receipt with its data hash, spec hash, seed and costs, checked in the browser. **Duplicate read surface (closed 2026-11-07).** The `/app/backtests` screen now hosts the authenticated LLM strategy launcher and the multi-run Monte Carlo comparison; the in-lab Backtester panel and its Backtests tab are removed. `e2e/chat-proposal.spec.ts` pins the authenticated launch/poll request and the selected-run Monte Carlo request. The legacy `POST /strategies/{id}/backtest` job route was deleted on 2026-11-08: it fetched no market data and executed a constant `100/105/95` OHLC frame behind a `TODO` placeholder, and its only UI was an unwired tab with a no-op Run button. Real strategy runs already go through `POST /backtest/run` with a receipt, so the duplicate fabricated path was removed rather than left claiming results. Two gaps remain, recorded rather than papered over:

1. **API image ≤ 600 MB and boot gate (open, unmeasurable here).** No container runtime is installed on the development machine — `docker`, `podman`, `nerdctl`, `colima` and `finch` are all absent — so the Dockerfile's `HEALTHCHECK` and size budget can only be verified on a Docker host or in CI: `docker build -t gateway-api quant-app-v1/backend && docker image inspect gateway-api --format '{{.Size}}'`. `ci.yml` currently builds no image, so the gate fails closed until such a job exists.
2. **Two-account RLS isolation (half closed).** The policy shape is now machine-checked offline: `tests/test_rls_schema.py` asserts RLS on every table, exactly one owner policy per table, `using` + `with check` on `auth.uid()`, parent-derived ownership for child rows, and no anon/public or `true` grant. Runtime isolation — anonymous reads return zero rows and account B cannot read account A — still needs a live Supabase project with two real accounts.

### P5 — Quant modules

**Status: implemented (2026-11-07) — §5.1 Monte Carlo, §5.2 Black-Scholes and §5.3 order book are implemented end to end, and all three surfaces have now been exercised in a browser through the app's own navigation (`e2e/order-book.spec.ts`, `e2e/monte-carlo.spec.ts`, `e2e/options.spec.ts`).**

**Goal:** the three differentiators, to spec.
**Depends on:** P4 (needs run data), independent of P6.

Deliverables: §5.1 with FR-M1..M7; §5.2 with FR-O1..O6; §5.3 with FR-L1..L6; UI surfaces for all three.

**Exit gate:** every validation item in §5.1, §5.2 and §5.3 passes as an automated test; seed determinism proven by hash comparison; order-book panel renders the horizontal histogram with the simulation label permanently visible.

**Record (2026-11-07) — §5.1 Monte Carlo:** `app/services/quant_monte_carlo.py` (engine `mc-1.0.0`) implements both methods on one `numpy.random.Generator(PCG64(seed))`: `gbm` fits μ and σ from the input log-returns and applies `r_t = (μ − σ²/2)Δt + σ√Δt·Z_t` with Δt = 1/periods-per-year, and `bootstrap` (the default) is a stationary block bootstrap of the observed log-returns with expected block length 20 and wrap-around. `POST /quant/monte-carlo` takes an owner-scoped run id — another account's id is a 404, not a permission error — **or** an explicit return series or equity curve, and refuses any other combination with a 400 that names what to supply. It returns the 5/25/50/75/95 percentile fan at every step, a 60-bin terminal histogram with its mean and standard deviation, VaR and CVaR at 95 and 99 as positive losses (`CVaR ≥ VaR` by construction), the per-path max-drawdown distribution (p50/p95/p99/worst plus a 24-bin histogram for the UI), P(ruin) against a threshold expressed as a fraction of starting equity with the median first-crossing bar, and the FR-M7 sizing suggestion — the largest 0.05-step multiplier up to 3× whose `k · CVaR_99` stays inside the caller's budget, or 0 with an explanation when even one step breaks it. The response echoes seed, paths, horizon, method, block length, data hash, output hash and engine version; identical inputs produce a byte-identical payload, which is what the determinism test compares. Caps: 50 000 paths, 2 000 bars, 8 000 000 simulated points and 1 000 block length, refused with a 400 rather than an OOM; 10 000 paths × 250 bars runs in well under the 5-second NFR-3 budget. `tests/test_quant_monte_carlo.py` covers all five §5.1 validation items — zero-volatility collapse to the deterministic curve, 50 000-path terminal mean within 1% and standard deviation within 2% of the analytic log-normal values, tail ordering, seed-hash determinism and both ruin boundaries — plus every input bound and the route's ownership, source-selection and error mapping. The report screen gained a **Monte Carlo** tab: seed/method/paths/horizon/budget controls, the percentile fan, the drawdown histogram, the VaR/CVaR and ruin table, the sizing sentence and the permanent simulation label, with the run's own data and output hashes shown so a fan on screen is traceable to the inputs behind it. Typecheck and the production build pass. The tab is no longer the only surface: **Monte Carlo** now has its own view (`/app/monte-carlo`, `MonteCarloView.tsx`) in the workspace rail beside Order book and Risk, reachable without a stored run. It fetches the selected symbol's last 250 daily bars, derives simple per-bar returns from those real closes, starts the paths at the last close and posts `returns` + `start_equity` to the same route (the engine log-transforms them), so no price is entered or invented on the client. `e2e/monte-carlo.spec.ts` drives Overview → Monte Carlo through the app's own navigation and pins the authenticated request (39 bar-derived returns, `start_equity` equal to the last close, no `run_id`), the fan and drawdown charts, the VaR/CVaR and ruin table, the source line and the permanent simulation label; the report tab still resamples a stored run and `e2e/chat-proposal.spec.ts` pins that path. Browser-verified 2026-11-07 against the running backend: AAPL's last 250 daily bars produced 249 observations from a 342.37 start, 10 000 paths over 249 bars, VaR 95 28.32 and CVaR 99 84.42, two charts and zero placeholders.

**Record (2026-11-07) — §5.2 Black-Scholes:** `app/services/quant_options.py` (engine `bs-1.0.0`) prices European calls and puts from the SRS formulas with continuous yield `q` and continuously compounded `r`, returns `d1`/`d2`, the fair value, the discounted intrinsic and time value, the full greeks under the SRS reporting conventions (theta per calendar day, vega and rho per 1%) with their units spelled out, the no-arbitrage band, a `near_expiry_unstable` flag for anything under one day to expiry, and the five FR-O4 model boundaries as a list on **every** response. `POST /quant/options/price` and `POST /quant/options/implied-vol` accept exactly the FR-O1/O2 inputs; a bad `S`, `K`, `T`, `r`, `q`, `sigma` or `type` returns 400 with `detail.field` naming the offender, never a NaN or an Infinity. Implied volatility solves `BS(σ) = market_price` on `[1e-4, 5]` with a self-contained Brent implementation (no SciPy) at `1e-8` on σ, falls back to bisection, and reports `converged`, `iterations`, `solver`, `model_price` and `price_error` rather than implying success. A price below `max(0, intrinsic)` or above the call's `S·e^(−qT)` / the put's `K·e^(−rT)` is refused with 422 `price_below_intrinsic` / `price_above_upper_bound` carrying the violated bound; a price exactly at intrinsic returns σ = 0 from the boundary, and one at the asymptotic upper bound returns σ at the search ceiling with `converged: false`. A 1e-8 guard on those bounds absorbs the 10-dp rounding of returned prices without clamping a real violation. `tests/test_quant_options.py` covers all five §5.2 validation items: put-call parity within 1e-8 across five parameter sets, monotonicity in `S`/`σ`/`K` with delta bounds and non-negative gamma/vega over a 27-case grid, the IV round trip over 200 `(moneyness, T, σ)` cases per option type, finite non-negative values for deep out-of-the-money and near-expiry contracts (including `T = 1e-8`), and all five greeks against central finite differences at 1e-4 relative. Two conditioning facts are recorded rather than hidden: deep in-the-money contracts with a day to expiry have a price that is flat to machine precision, so the round-trip test asserts exact price recovery there and σ recovery wherever `dV/dσ` is meaningful, and a dedicated test pins the flat-price case. The **Options** view (`/app/options`, calculator component `OptionsCalculator.tsx`) shows fair value against a user-entered market price, the difference in currency, the implied volatility of that market price with its convergence status, and the IV difference in volatility points against the entered σ (FR-O5), alongside the greeks table, the band and the model boundaries. No options chain or market data is used anywhere (FR-O6). Typecheck and the production build pass. The view has now been exercised in a browser: `e2e/options.spec.ts` opens Options from the workspace rail, prices the default 100/100/0.25-year/5%/20% call through the authenticated `/quant/options/price` and `/quant/options/implied-vol` routes, and pins the fair value against the market price, their currency difference, the implied volatility with its convergence status and solver, the IV difference in volatility points, the greeks table and the no-arbitrage band. Browser-verified 2026-11-07 against the running backend: fair value 4.6150, delta 0.5695, implied volatility 22.98% converged in 6 Brent iterations.

**Record (2026-11-07) — §5.3 simulated order book:** `app/services/quant_orderbook.py` (engine `ob-1.0.0`) instantiates the archetype population from one `PCG64(seed)` stream — market makers at 0.40, momentum at 0.20, noise at 0.30 and large passive at 0.10, weights configurable and normalised — and lets each agent emit one `(side, price, size)` quote per the §5.3 rules. Market makers draw half-spreads from `N(spread_base, spread_cv)` around the mid and shrink their quoted size by `1/(1 + inventory_penalty·|inventory|)` while skewing the side they quote toward reducing the inventory they hold; momentum quotes on the side of the recent return with size proportional to `min(|z|, 3)`; noise quotes a random side with lognormal size inside ±`band`; large passive blocks sit at `large_distance` (default 0.5%) or further with a top-decile size. Quotes snap to the tick grid strictly below or above the mid, so the ladder cannot cross regardless of tick, spread or band — `crossed` is reported and is always false. Aggregation sums size into price bins **by archetype** and keeps the contributing agent count per segment, so every level can be expanded to show who is behind it (FR-L3). The caps of 200 levels per side and 50 segments per level (FR-L6) are enforced after aggregation and are honest about what they hide: `total_size`, `visible_size`, `dropped_size` and `conservation_delta` prove no size was invented or lost, with the emitted total equal to visible plus dropped. The payload carries `simulated: true` and the literal label "Simulated liquidity — not exchange data", the mid, best bid/ask, spread in ticks, seed, agents, all parameters and an `output_hash`, so the same inputs and seed reproduce a byte-identical ladder. `POST /quant/orderbook/simulate` takes the price context (mid, recent and lookback returns, lookback volatility, inventory) plus the population and parameter overrides, and returns 400 with `detail.field` for anything invalid — mid ≤ 0, agents outside 10..5 000, a negative weight, a tick larger than the mid, a band above 50%, a large-passive distance under 0.5%. `tests/test_quant_orderbook.py` covers all five §5.3 validation items: identical hashes for identical seeds and different ones for different seeds, conservation through aggregation and through truncation, the market-maker share falling monotonically as `|inventory|` rises with the flat book quoting both sides evenly, the ladder never crossing across eight adversarial parameter sets including a one-cent tick and a single-archetype population, and the FR-L6 caps at 5 000 agents, plus the sub-second NFR-3 budget and the route's error mapping. The **Order book** view (`/app/orderbook`, `OrderBookPanel.tsx`) draws the horizontal histogram with price descending on the vertical axis, bids extending left and asks right from the mid axis, stacked by archetype in a stable colour with a legend, a hover breakdown of size, share of side and contributors, and a click-through derivation table (contributions, agent counts, parameters, seed, hash). "Simulated liquidity — not exchange data" is a permanent band at the top of the panel, not a tooltip (FR-L4). The price context is no longer typed in: the panel reads the chart's selected symbol's last 60 daily bars, takes the last close as the mid and derives the one-bar return, the 20-bar return and the 20-bar return volatility from those bars (a flat series falls back to 1% so the engine still has a positive denominator), re-simulating whenever the symbol or the bars change and showing the bar date and every derived value as read-only context. Population controls (agents, seed, market-maker inventory) stay user-set, and a symbol with no usable daily bars explains itself with a retry instead of simulating against a missing price. **Browser check (2026-11-07):** the panel was opened from the workspace navigation against a running engine and drew both sides of a live 167-level ladder (91 bids / 76 asks, a 3-tick spread and 929 760.55 visible size); clicking a level showed its archetype derivation and the "Simulated liquidity — not exchange data" band stayed visible. The summary strip now also reports spread in currency alongside ticks and the visible bid/ask depth, both summed from the returned levels. `e2e/order-book.spec.ts` pins the navigation, the authenticated simulate request whose mid is the selected symbol's last daily close, the rendered bid/ask bars, spread and per-side depth, and the level derivation table, closing this exit-gate item.

### P6 — Hardening and launch

**Goal:** safe to expose publicly.
**Depends on:** P4, P5.

Deliverables: NFR-6..NFR-19 (security baseline, including the carried-forward remediation items); NFR-20..NFR-22; NFR-23..NFR-26; NFR-27..NFR-30; dependency audit; `robots.txt` + minimal sitemap.

**Exit gate:** security checklist signed off item by item; foreign-origin mutation returns 403; operator allowlist fails closed when empty; disclaimers present on every results surface; audit clean; the site is reachable over HTTPS on the deployed frontend origin with the API on its own origin.

**Status (2026-11-07): NFR-6..NFR-19 audited and every finding remediated — 12 pass, 0 partial, 0 fail, 2 pass with caveat. OpenBB is recorded as removed, not as an error-text target. The NFR-20..NFR-30 audit is complete — all 11 pass; Phase D is closed.**

| ID | Verdict | Evidence and gap |
| --- | --- | --- |
| NFR-6 | **Pass** | Backtest, quant, bot and agentic-lab routes derive ownership from `CurrentUser`, and `app/api/v1/portfolio.py` now does too: every handler takes the principal, the default book is `paper_<user.id>` (created on first use and rejected with 409 if the id belongs to someone else), cross-owner reads return 404, and the LLM context feeder threads the same principal. `request.user_id` remains the member being invited, not the acting principal. `tests/test_portfolio_ownership.py` covers per-user books and cross-owner rejection. Strategy Studio follows the same rule: every `/strategies` route takes `CurrentUser`, stores `owner_id` on create and filters by it, so another account's id is a 404 (`tests/test_strategies_ownership.py`), and the surface is no longer gated. The remaining shared stores (`/journal`, `/ai-trading`, `/vault`, `/llm`, and `/portfolio` except `/risk`) still answer 503 until their owner-scoped repositories ship. |
| NFR-7 | **Pass** | Owner-scoped lookups (`get_backtest_receipt(run_id, owner_id)`, `_own_run`, quant run lookup) return 404 for another account; tests cover the cross-owner case in `test_quant_monte_carlo.py`, `test_quant_orderbook.py` and the backtest suite. Shared private stores (`/portfolio`, `/strategies`, `/journal`, `/ai-trading`, `/vault`, `/llm`) are denied 503 rather than exposed. |
| NFR-8 | **Pass** | `app/auth.py::_operator_identities` parses exact `{issuer, subject}` pairs from `GATEWAY_OPERATOR_USER_IDS`, and an absent, malformed, wrong-shaped or duplicated list returns an empty set, so `require_operator` and the middleware's `/risk` and `/settings/providers` gate answer 403. **Name drift:** the requirement says `GATEWAY_OPERATOR_IDS`; the code reads `GATEWAY_OPERATOR_USER_IDS`. |
| NFR-9 | **Pass** | All five headers are set in `SecurityHeadersMiddleware`, and the policy now comes from `content_security_policy(env)` (`app/api/main.py`): production emits `script-src 'self'` with no `unsafe-inline` or `unsafe-eval`, while local/test keep Vite's inline/eval needs. `tests/test_security_hardening.py` covers both profiles and the header on a served response. |
| NFR-10 | **Pass** | The shared limiter lives in `app/api/rate_limit.py` (240/minute, 3000/hour), `SlowAPIMiddleware` is installed in `main.py`, and `/auth/register` plus `/auth/login` carry a stricter 10/minute route limit. `tests/test_security_hardening.py` asserts the middleware is registered and drives 11 login attempts to a 429. |
| NFR-11 | **Pass** | The OpenBB integration is **removed, not patched**: `app/api/openbb_routes.py`, both OpenBB providers, the OpenBB CLI, the feature flags, provenance entries and the frontend mention are gone, so no handler reflects upstream exception text. The remaining `detail=str(exc)` sites are domain errors; provider failures are logged server-side. `tests/test_security_hardening.py` asserts the modules and `/openbb/*` routes cannot reappear. |
| NFR-12 | **Pass** | Collections are bounded before allocation: history ≤ 20 000 bars, backtests ≤ 5 000 bars per symbol, MC ≤ 50 000 paths × 2 000 bars with an 8 000 000-point guard, order book ≤ 5 000 agents, chat messages ≤ 80 × 100 000 chars, vault values ≤ 4 096. The two former gaps are closed: `MonteCarloRequest.returns` / `equity_curve` cap at `MAX_OBSERVATIONS = 20 000` in both the Pydantic model and `_validate_series`, and `kronos_service.forecast` refuses more than `MAX_BARS = 2 000` history candles on both the local-server and in-process paths, with `/forecast/kronos` mapping it to 422. `tests/test_resource_bounds.py` covers all four. |
| NFR-13 | **Pass** | `app/services/kronos_installer.py` is a fail-closed stub — `status()` always reports disabled, `start_install()` always raises — and `POST /forecast/kronos/install` answers 503 before doing any work. `bandit -lll` reports no `subprocess`, `os.system` or `pip install` call in `app/`. |
| NFR-14 | **Pass (with caveat)** | The browser bundle only exposes `VITE_SUPABASE_URL`, the publishable `VITE_SUPABASE_ANON_KEY` and the API base; provider keys are written server-side and returned only as status. `.env.docker` is no longer tracked: the committed `.env.docker.example` carries placeholder `JWT_SECRET_KEY`/`POSTGRES_PASSWORD`, the real file is ignored, and `docker-compose.yml` documents copying the example. **Caveat:** the old values remain in git history, so both secrets must be rotated before deployment (and history purged if this repository has ever been public). |
| NFR-15 | **Pass (with caveat)** | `frontend/src/lib/markdown.tsx` is a dependency-free tokenizer with a bounded regex, a 5 000-iteration guard, no `dangerouslySetInnerHTML`, and an allowlist for link schemes; the backend never renders markup. Inbound chat is bounded (80 messages × 100 000 chars), tool output is truncated to 12 000 chars, and the SSE harness now enforces a 100 000-character aggregate cap across all tool rounds (`MAX_REPLY_CHARS` in `app/api/v1/llm.py`): it truncates at the boundary, emits an error event and abandons the provider stream. `test_chat_stream_stops_at_aggregate_reply_cap` covers the handler and `test_chat_cap_streams_through_http_when_private_gate_is_lifted` drives the same cap over the SSE route with the gate bypassed. **Caveat:** no live-provider SSE run has been recorded — `scripts/smoke_chat_stream.py` is the runner for that check, but no provider key is configured on this machine, so it exits 2 before contacting a provider. The offline route test uses a fake provider, so it proves the cap and transport logic, not provider interoperability. |
| NFR-16 | **Pass** | `pip-audit -r quant-app-v1/backend/requirements-full.txt` reports **no known vulnerabilities**: FastAPI 0.162.0 / Starlette 1.10, aiohttp 3.14.5, cryptography 50.0.2, orjson 3.13.0, python-multipart 0.0.33, Flask 3.1.3 and python-dotenv 1.2.2 are pinned. `python-jose` was replaced by PyJWT, which removes `ecdsa` (no fixed release) and the stale `pyasn1` from the tree. `npm audit --omit=dev --audit-level=high` reports **0 vulnerabilities** on React Router 7.18.5. `bandit -r app -lll` reports **0 high**: the SHA-1 event ids declare `usedforsecurity=False` because they are dedupe keys, not security hashes. CI now gates all three. Dev-only Vite/launch-editor advisories remain outside the production `--omit=dev` gate. |
| NFR-17 | **Pass** | Demo-trading, backtest-receipt and bot tables are distinct stores in `app/services/database.py`; broker SDKs are gone and `tests/test_p4_demo_trading.py` asserts zero broker imports and that the removed modules cannot reappear. |
| NFR-18 | **Pass** | Receipts are inserted once under a server-generated `run_id`; no route updates a receipt and no `UPDATE backtest_receipts` exists. `save_backtest_receipt` now uses a plain `INSERT` instead of `INSERT OR REPLACE`: a re-used id raises `ValueError` and leaves the stored receipt untouched, so provenance cannot be silently rewritten. Retention still prunes an owner's receipts beyond 50 (`RECEIPT_RETENTION`). `tests/test_p4_receipts.py::test_receipts_are_insert_only` covers the refusal and the preserved row. |
| NFR-19 | **Pass** | `visible_runs`, `get_run_for_user` and `delete_run` now require an exact `owner_user_id` match (`app/services/lab_backtest.py`); ownerless rows are quarantined — invisible and undeletable — pending an operator migration, matching DR-6/DR-7. `tests/test_agentic_lab.py` and `tests/test_security_hardening.py` cover the ownerless case. |

**NFR-20..NFR-30 audit (2026-11-07, in progress):**

| ID | Verdict | Evidence and gap |
| --- | --- | --- |
| NFR-20 | **Pass** | `GET /health` and `GET /health/ready` return one machine-readable readiness report: `status`, `service`, `version`, `environment`, `execution_mode`, `capabilities`, and a `components.database` entry with `status`, a fixed `detail`, and `latency_ms`. The probe opens the SQLite store and runs `SELECT 1`; any failure returns HTTP 503 with `status: degraded` and `database: failed`, keeping exception text out of the body. `GET /health/live` stays a dependency-free 200 for liveness. `tests/test_health.py` drives the real ASGI app through the healthy path, a broken database (both readiness endpoints 503), and liveness while the database is down. |
| NFR-21 | **Pass** | `app/api/observability.py` installs `RequestLoggingMiddleware` as the outermost middleware: every HTTP response, including 401/403/429 and CORS preflight, carries `X-Request-ID` — a validated client id of 8–64 `[A-Za-z0-9._-]` characters, otherwise a fresh UUID hex — and emits one structured record with `request_id`, `method`, `path`, `status` and `duration_ms`. Headers, query strings and bodies are never logged, so bearer tokens, provider keys and emails cannot leak; CORS exposes the id to browsers. `tests/test_observability.py` drives real ASGI requests and asserts the record fields, replacement of a malformed id, and that an authorization header plus a token-bearing query never appear. |
| NFR-22 | **Pass** | Aggregation is opt-in and off by default: `ErrorAggregator.from_env()` reads `ERROR_AGGREGATION_ENABLED` (unset = disabled). When enabled, `ErrorAggregator.capture` emits one structured `aggregated_error` event carrying `error_id`, `error_type`, `message`, `request_id`, `method`, `path` and `status_code`; `scrub_error_text` masks email addresses and bearer/token/api-key/secret/password assignments before anything is logged, and headers/bodies are never included. Every unhandled exception now returns a fixed `{"detail": "Internal server error", "request_id": …}` body with `X-Request-ID`, never exception text. `tests/test_error_aggregation.py` drives validation, unknown-route and unhandled-exception requests against the real ASGI app and asserts the scrubbed event plus off-by-default silence; `tests/test_health.py` covers the dependency-down 503 path. | NFR-23 | **Pass** | `App.tsx` keeps ⌘K/Ctrl-K global; `CommandPalette` is a `role="dialog"` with `aria-modal`, a `combobox` input tracking `aria-activedescendant`, arrow/Enter navigation, a Tab trap and focus restoration. The brand is a keyboard-operable button, and strategy cards, version rows, journal rows and overview watchlist rows respond to Enter/Space as well as clicks. `e2e/accessibility.spec.ts` opens the palette with Control+K, checks focus and the active descendant, traps Tab, activates a command and asserts navigation. |
| NFR-24 | **Pass** | Ticker chips carry signed percentages (`+0.17%` / `-0.54%`) and ▲/▼ markers, so the direction is in the accessible name even though the arrows are decorative. The risk summary is labelled “Risk” with numeric metrics and High/Medium/Low text, and paper surfaces carry explicit “Paper”/“simulated” labels. No code change was needed for this requirement; it was audited alongside the others. |
| NFR-25 | **Pass** | A new `max-width: 1024px` rule collapses both side shells to 52 px icon rails and hides resize handles, and `App.tsx` passes `collapsed` through `matchMedia("(max-width: 1024px)")`, keeping one usable content column at exactly 1024 px. `e2e/accessibility.spec.ts` sets a 1024 px viewport and asserts each rail is ≤60 px while the center canvas is ≥900 px. |
| NFR-26 | **Pass** | Primary and secondary text measure 18.96:1 and 7.36:1 on the dark canvas; `--text-muted` was raised from `#71717a` (3.67–4.09:1) to `#8b8b93` (5.24–5.85:1). The global `*:focus-visible` ring is 2 px accent, with a dedicated command-input ring. `e2e/accessibility.spec.ts` computes the muted-token contrast in the rendered page and asserts a focused control has an outline of at least 2 px. |

| NFR-27 | **Pass** | `LegalNotice` is mounted in `AppShell` for every `/app/*` view and repeated in the landing footer. The notice states results are simulated and historical, not investment advice, that past performance does not predict future results, and that only paper execution is available. `e2e/legal.spec.ts` asserts the persistent `Legal notice` content on the real rendered page, both before and after acceptance. |
| NFR-28 | **Pass** | Each surface carries its own line: `Backtester.tsx` labels the studio “Historical only” and theoretical P&L “Simulated on historical bars — hypothetical, not realised”; `MonteCarloPanel.tsx` opens with “Simulation, not a forecast” plus the resampling/overfitting disclaimer; `OrderBookPanel.tsx` states the ladder is built “from seeded agent quotes, not from an exchange, broker or order-book feed.” No new copy was needed; this requirement was audited and is covered by the existing surfaces. |
| NFR-29 | **Pass** | New `notice_acceptances` table plus authenticated `GET/POST /notices` (`app/api/v1/notices.py`); `NoticeAcceptanceGate` fetches the user's status on sign-in and shows the dialog only when the current version is unaccepted, then records the acknowledgement. `tests/test_notice_acceptance.py` proves unauth 401, first-use false, persistence, idempotent re-acceptance and per-user isolation; `e2e/legal.spec.ts` drives first-use accept and the already-accepted path. Persistence is local SQLite when Supabase is disabled and `notice_acceptances` / `gw_get_notice_acceptance` / `gw_accept_notice` when it is enabled; the table, RLS policy and RPCs are in `supabase/schema.sql`. |
| NFR-30 | **Pass** | Removed the “LIVE broker (real funds!)” route claim from `AiTrading.tsx` (now a disabled “Live broker (unavailable)” option with an explicit unavailable warning) and removed “live feeds”/“live chart”/“streamed live” marketing claims, replacing them with market-data wording. Remaining “live” strings are quote-freshness labels, data-feed wording or explicit “Live execution unavailable” states; no accuracy/profitability guarantee or live-trading claim remains in the UI, and the document metadata is only “Gateway”. |

No NFR-27..NFR-30 item is credential-blocked; the only outstanding deployment note is the Supabase mirror for NFR-29. |

**Prioritised remediation** (all items applied 2026-11-07):

1. **Secrets (NFR-14): applied** — `.env.docker` is untracked and ignored; `.env.docker.example` holds placeholders and compose documents the copy step. **Old values remain in git history**, so rotate `JWT_SECRET_KEY` and the Postgres password before any deployment and purge history if the repository has ever been public.
2. **Dependencies (NFR-16): applied** — upgraded FastAPI/Starlette, aiohttp, cryptography, orjson, python-multipart, Flask, python-dotenv and scipy; replaced `python-jose` with PyJWT to drop `ecdsa`/`pyasn1`; upgraded React Router to 7.18.5; marked SHA-1 dedupe ids `usedforsecurity=False`; added `pip-audit`, `bandit -lll` and `npm audit --omit=dev --audit-level=high` as CI gates.
3. **Rate limiting (NFR-10): applied** — `SlowAPIMiddleware` now runs the default budget and `/auth/register` + `/auth/login` carry a 10/minute route limit; the 429 path is covered by `tests/test_security_hardening.py`.
4. **CSP (NFR-9): applied** — `content_security_policy(env)` drops `unsafe-inline` and `unsafe-eval` from `script-src` in production and keeps them only for local/test Vite builds.
5. **OpenBB (NFR-11): applied by removal** — the module, providers, CLI, flags, provenance keys and `/openbb/*` mount were deleted; this supersedes the earlier "fixed message" plan. Docs corrected to record the removal.
6. **Legacy lab runs (NFR-19): applied** — ownerless runs are quarantined instead of shared; `visible_runs`/`get_run_for_user`/`delete_run` require an exact owner match.
7. **Unbounded inputs (NFR-12): applied** — Monte Carlo accepts at most 20 000 return/equity observations, and Kronos accepts at most 2 000 history candles in both service paths.
8. **Portfolio principal (NFR-6): applied** — every portfolio handler takes `CurrentUser`; the default book is `paper_<user.id>` with an ownership check, cross-owner lookups 404, and the LLM context feeder uses the same principal. The HTTP gate still answers 503 until owner-scoped repositories ship.

**P6 deliverable check:** `robots.txt` and `sitemap.xml` are generated into the Cloudflare build output (`dist/`) by `quant-app-v1/frontend/vite.config.ts` from `VITE_SITE_URL`, so the committed placeholder-host copies under the unserved root `public/` are gone. Robots allows `/` and disallows only `/secrets/` and `/admin/` — the repository-path disallow was removed — and the sitemap lists only SPA routes under the configured origin. Neither the HTTPS frontend origin nor foreign-origin 403 could be measured in this audit; both need a running deployed stack. The same audit added `scripts/smoke_chat_stream.py` for a live SSE run; it is blocked on a provider key, as recorded in `docs/deployment.md` §5 and [`PLAN.md`](PLAN.md).

---

## 10. Risks, assumptions and open decisions

### Open decisions

| # | Decision | Status | Impact if unresolved |
| --- | --- | --- | --- |
| O-1 | **Which container host runs the API.** Cloudflare cannot execute Python; its static hosting is static-only. Requirements: HTTP + WebSocket, custom domain behind Cloudflare proxy, ≤ 600 MB image, low fixed cost, single region acceptable. | **Open** — provider catalogue returned no viable candidate; do not select by default | P1 blocks; everything downstream blocks |
| O-2 | Which single market-data source is supported at launch (Yahoo keyless vs. a keyed provider with a free tier). | **Open**, default Yahoo (`yfinance`) | FR-D1 wording |
| O-3 | Whether the AI harness / Agentic Lab is deleted or kept disabled after P6. | **Deferred** to P6 review | Repo size, not correctness |

### Assumptions

| # | Assumption | If wrong |
| --- | --- | --- |
| A-1 | Public delayed data is sufficient for backtesting demonstrations. | A paid feed is required; FR-D1 changes. |
| A-2 | Supabase free/low tier supports the expected row counts (≤ 50 runs/user, ≤ 20 000 bars/batch). | Retention caps tighten. |
| A-3 | Users accept that every number is simulated. | The product premise fails; revisit §1.1. |
| A-4 | A single-region API at ≤ 50 concurrent users is acceptable. | Autoscaling and a cost model are needed. |

### Risks

| Risk | Mitigation |
| --- | --- |
| The API container host is chosen late, blocking P1. | Resolve O-1 before P1 ends; the SRS pins only the requirements, not the vendor. |
| Backtest results are believed as forecasts. | Receipts, OOS split, Monte Carlo, and NFR-27/28 language. |
| The simulated ladder is mistaken for market data. | `simulated: true` in the payload, permanent on-panel label, derivation disclosure (FR-L4). |
| RLS mistakes leak data. | Two-account isolation tests as a P2 gate and again at P6. |

---

## 11. Traceability

Nothing was silently dropped. Each superseded document maps to a disposition.

| Superseded doc | Survived into | Cut | Deferred |
| --- | --- | --- | --- |
| `phase-0-plan.md` | §3.3 environments, §4.2 provenance, FR-A5, NFR-20 | Alpaca-only framing, execution guards | — |
| `phase-1-plan.md` | §4.3 workspace, FR-W1..W5 | Scanner presets (6 categories), command palette expansion | Saved screens |
| `phase-2-plan.md` | FR-D1..D7 | Licensed calendar/news, event snapshots, source-health dashboards | Event-aware backtesting |
| `phase-3-plan.md` | §4.4, §4.5, FR-S1..S5, FR-B1..B8 | Visual strategy builder, parameter-sensitivity sweeps, promotion lifecycle | Walk-forward optimisation |
| `phase-4-plan.md` | §4.6, FR-T1..T7 | Broker-origin fill ledger, ≥ 1 000-fill evidence gate | — |
| `phase-5-plan.md` | Nothing (removed) | Entire live-execution scope | — |
| `phase-5-prerequisites.md` | §9 dependency chain re-expressed as P1..P6 | Live gate priorities | — |
| `phase-6-plan.md` | Nothing (removed) | OpenBB context, AGPL review, context server | — |
| `phase-7-plan.md` | NFR-9, NFR-27..NFR-30, minimal robots/sitemap | 215-line SEO programme, backlink strategy, cookie banner | Analytics |
| `phase-8-plan.md` / `phase-8-draft.md` | Supabase only (§3, §7) | Stripe, Resend, Sentry, Vercel, Auth0, Cloudflare-WAF programme | — |
| `phase-9-plan.md` | §10 O-3 | MCP/agent interface, Phase 5 unblock | AI harness |
| `gateway-roadmap.md` | §1.1 thesis, §6.5 UX principles, §6.6 disclaimers | Live-capability phases, competitive benchmark | — |
| `auth0.md` | Nothing (removed) | Entire dual-auth design | — |
| `status.md` | §3.4 measured build facts, §9 gates | Per-feature completion ledger | — |
| `security.md`, `backups.md`, `monitoring.md`, `legal.md` (0-byte stubs) | NFR-6..NFR-22, §6.6 | — | Backup/DR programme |
| `terms.md` | NFR-27..NFR-30 | Phase-scoped legal text, broker disclaimers | Full ToS |
| `analytics.md`, `cookie.md`, `llms.txt` (placeholders) | — | All | Analytics + consent |

---

## 12. Acceptance of this document

This SRS is approved as the product baseline. Implementation proceeds through P1 → P6, each gated on its exit criteria. Any requirement change edits this document first; the phase order does not change without amending §9.

Changes to §5 require a version bump and re-running the validation suites, because the numbers those modules produce are the product.
