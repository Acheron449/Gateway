# Gateway product roadmap

_Product assessment: 19 September 2026; execution safety status reconciled 18 October 2026_

## Product thesis

Gateway should become an **evidence-first research-to-execution workspace** for active traders: one calm place to discover an opportunity, understand its market and event context, create an explicit strategy, validate it with reproducible backtests, and then paper-trade it before any live deployment.

This is a more focused promise than trying to recreate every competitor. Gateway should borrow the best of the market scanner, the research terminal, and the quant engine while making the chain of evidence visible at every hand-off.

```text
Discover → Investigate → Define → Validate → Paper trade → Deploy → Review
   scanner       chart       strategy     backtest       execution     journal
```

## Current position

Gateway is an early functional foundation rather than a production trading platform. The 2026-10-18 paper-safety increment makes broker execution fail closed and clarifies that the paper desk is simulated; it does not establish live-trading readiness or Phase 4 reconciliation evidence.

| Area | What exists | What is still required |
| --- | --- | --- |
| Market workspace | React/Vite dashboard with symbol selector, symbol search, history, chart, WebSocket updates, RSI and pattern display | A real multi-asset universe, reliable live feeds, workspace persistence, watchlists, alerts, screeners and responsive product navigation |
| Analysis | Indicators, head-and-shoulders recognition, sentiment/impact model, optional Kronos forecast endpoint | Model validation, explainability, more patterns/indicators, feature store and independent out-of-sample evaluation |
| News & macro | A Forex Factory helper and macro-provider scaffolding; provider and calendar/news paths exist | Licensed structured calendar/event data, source health monitoring, event-to-instrument mapping, historical archive and news-aware backtesting |
| Backtesting | Job endpoint, risk manager, fill simulation and persistence; StrategySpec and version storage | Complete deterministic engine, realistic data/cost acceptance, portfolio handling, benchmark/reporting suite, walk-forward/OOS evidence and repeatable receipts |
| Execution | Simulated paper portfolio/order path; guarded Alpaca execution adapters whose placement methods fail closed; `/live` API routes unmounted | Durable broker-order intent/recovery; broker-origin fill ingestion; independent comparator; ≥1,000 settled real paper fills with <0.1% discrepancy; security/legal/ownership review and written authorization; no live execution enabled |
| Product experience | Early React dashboard plus legacy Flask pages for auth/landing/main app | One product shell, real auth/RBAC, user data model, QA, observability and production deployment |

### Important current constraints

- `BrokerService` may fall back to simulated fills; it is not proof of live-trading readiness.
- Broker order-placement methods are deliberately disabled until durable intent/recovery is implemented; no broker orders or API calls were made for this increment.
- The central orchestrator still uses placeholder symbol, price and quantity values, so it must not be connected to live capital.
- The Forex Factory integration can return scraped snippets or curated fallback copy. It must not be presented as an authoritative real-time news feed.
- The market search universe is six hard-coded equities; the application does not yet support the multi-asset scope shown in the older screens.
- The optional Kronos model needs a separately configured source checkout before its endpoint becomes available.
- Phase 4 reconciliation is **not verified**. The paper desk is simulated; no broker-origin fill ledger or reviewed comparator currently exists. Sample fixtures or synthetic trade rows do not satisfy the real evidence gate.
- Live execution is **blocked**. The `/live` API router is deliberately unmounted, direct order placement fails closed, and identity/ownership, security, legal, account eligibility, durable recovery, reconciliation and explicit written authorization gates remain open.

## Competitive benchmark and resulting priorities

| Reference | Useful benchmark | Gateway gap | Gateway response |
|---|---|---|---|
| [Algory](https://algory.app/) | Strategy-vault lifecycle, survivor ranking, out-of-sample checks, portfolio correlation and explicit forward-test/deploy flow | Gateway has a basic backtester but no strategy registry, promotion criteria or portfolio-level evidence | Build a **Strategy Vault** with immutable versions, OOS/walk-forward reports, degradation monitoring and a paper-first promotion gate |
| [Finviz](https://finviz.com/) | Fast discovery through screeners, maps, market breadth, news, calendar, groups and asset views | No discovery surface, filters, saved screens, heatmap, market breadth or alerting | Make **Scanner** the first home screen: presets, saved queries, market regimes, catalyst filters and one-click investigation |
| [NautilusTrader](https://nautilustrader.io/) | Consistent research/live runtime, adapter architecture, advanced orders, deterministic event replay and serious test discipline | Gateway’s execution and simulation layers are coupled to simple provider fallbacks and lack event sourcing/replay | Adopt its principle—not necessarily its stack—through canonical events, adapters, deterministic replay and integration/acceptance test suites |
| [OpenStock](https://github.com/Open-Dev-Society/OpenStock) | User foundations: secure auth, watchlists, command palette, profiles, daily summaries, polished market overview | Gateway has no durable user workspace in the React app | Add workspace/user model, saved watchlists/layouts, command palette, onboarding and notifications before broad feature expansion |
| [London Strategic Edge](https://londonstrategicedge.com/) and its [open projects](https://github.com/londonstrategicedge) | Broad historical data, macro coverage, backtesting/ML tools and a terminal-oriented workflow | Gateway lacks an explicit data catalogue, provenance, dataset versioning and broad asset coverage | Introduce a provider-agnostic **Data Catalog**, begin with a narrow licensed universe, then expand only after quality and entitlement controls are in place |
| [Forex Factory thread](https://www.forexfactory.com/thread/1247273-free-news-api-machine-learning-live-trading-and) | Event calendars are useful inputs to fundamental/news-aware strategies and historical testing | Current integration is best-effort scraping, which is fragile and unsuitable as a trading dependency | Use a licensed/permissioned structured provider or a documented official feed; retain source, timestamp, revision, timezone, event importance, historical values |

The clearest differentiation is **trustworthy workflow, not feature volume**: a trader can answer “what data, rules, assumptions, costs and events produced this result?” without leaving Gateway.

## Sequenced roadmap

### Phase 0 — Make the foundation trustworthy (0–4 weeks)

- Define canonical domain models: instrument, quote, candle, news item, economic event, order, fill, position, portfolio and provenance.
- Establish environment profiles (`dev`, `paper`, `live`) with live disabled by default, secrets outside source control and a health endpoint.
- Build the instrument catalogue and normalized symbol/search APIs; mark delayed, unavailable and unlicensed data honestly.
- Add data provenance to every response: source, retrieval time, market time, entitlement, delay, coverage and any fallback.

**Exit criteria:** app starts in paper-safe mode; providers can be replaced without UI rewrites; every displayed price/event exposes source and freshness; secrets are not committed.

### Phase 1 — Research workspace and discovery (4–8 weeks)

- Replace the scattered screens with a persistent shell: navigation, symbol workspace, chart and decision inspector.
- Build a real scanner with filter presets, saved screens and direct navigation into a symbol workspace.
- Add watchlists, layouts, user preferences and a command palette after choosing local versus managed authentication/storage.
- Make news and calendar cards readable and provenance-aware; remove raw payloads from user-facing surfaces.

**Exit criteria:** user can discover a symbol, inspect its chart/events and save/restore a workspace without seeing prototype controls or unlabelled data.

### Phase 2 — Data, news and macro context (8–14 weeks)

- Formalize provider interfaces, coverage/entitlement metadata, retry/fallback policy and freshness budgets.
- Integrate a licensed calendar/news source; retain historical event snapshots and revisions for replay.
- Add event markers, detail inspection and relevance mapping to the symbol workspace.
- Measure source health and surface degraded/fallback status rather than silently substituting data.

**Exit criteria:** each supported market has documented sources, freshness/coverage expectations and a traceable event history. Current implementation is only **partially verified** against these outcomes; see `docs/phase-2-plan.md` and `docs/phase-5-prerequisites.md`.

### Phase 3 — Strategy studio and credible backtesting (14–22 weeks)

- Make the strategy generator produce a typed strategy spec: market, timeframe, entry/exit, sizing, invalidation, session/event rules and assumptions.
- Add a visual strategy builder alongside the prompt interface. Users must approve normalized rules before a run.
- Upgrade simulation: commissions, bid/ask spread, slippage, latency, trading sessions, corporate actions where relevant, FX conversion and order semantics.
- Deliver metrics and diagnostics: equity curve, drawdown, exposures, trade distribution, turnover, benchmark, parameter sensitivity and per-regime/event results.
- Require train/validation/test splits, walk-forward optimization and randomized/Monte Carlo robustness checks before strategy promotion.
- Version datasets, strategy code/specs, engine version, parameters and results in an immutable Strategy Vault.

**Exit criteria:** every result has a reproducibility receipt; users can compare versions and see whether performance remains after realistic costs and unseen data. Strategy specs/version hashing exist, but complete Phase 3 acceptance remains **partially verified**.

### Phase 4 — Paper portfolio, risk and review loop (22–30 weeks)

**Current evidence (2026-10-18):** simulated portfolio/order features exist, but Phase 4 reconciliation acceptance is **not verified**. Broker-origin fill ingestion, an independent comparator and ≥1,000 settled real-fill evidence are not delivered. See `docs/phase-4-plan.md` and `docs/phase-5-prerequisites.md`.

- Build a paper portfolio ledger, positions, cash, P&L, orders, fills and portfolio exposures from canonical events.
- Add pre-trade controls: buying power, concentration, gross/net limits, max loss/day, kill switch, restricted instruments and event blackout rules.
- Add alerts for signals, calendar risk, order status, drawdown and strategy decay; begin with in-app/email rather than high-noise channels.
- Build a journal joining hypothesis, decision, chart/event context, execution, outcome and post-trade review.
- Implement strategy scorecards, paper-vs-backtest divergence and scheduled retraining/revalidation reminders.

**Exit criteria:** a strategy can be paper traded with complete reconciliation and a reviewer can trace every fill back to its strategy version, data and risk decision. The ≥1,000 settled real-fill / <0.1% discrepancy gate has not been met.

### Phase 5 — Controlled live capability and scale (30+ weeks)

**Current status (2026-10-18): BLOCKED.** Broker order placement fails closed pending durable intent/recovery, and the `/live` API router is deliberately unmounted. This increment authorizes no broker calls or live trading; evidence, identity/ownership, security, legal and written-authorization gates remain open.

- Add broker adapters one at a time, beginning with a single fully supported paper/live broker and asset class.
- Implement order state reconciliation, idempotency, partial fills, retries, market-data disconnect handling, account sync and incident runbooks.
- Enforce live activation gates: completed paper history, user acknowledgement, risk profile, limits, monitoring and reversible kill switch.
- Add event-sourced audit history and deterministic replay for strategy, order and fill incidents.
- Establish production operations: monitoring, alerting, backups, disaster recovery, security review, privacy policy, terms and jurisdiction-specific legal/compliance review.

**Exit criteria:** live orders are limited to eligible accounts and can be reconciled, audited and safely halted. Do not set a public live-trading date before this bar is met.

### Phase 6 — OpenBB context integration (retained, feature-gated)

- OpenBB is retained for quote/news/calendar context only; historical OHLCV adapters, routes, CLI commands and ingestion helpers are retired.
- Existing historical chart/backtest providers remain the source for historical prices.
- Production use remains gated on AGPLv3/legal review; `ENABLE_OPENBB_DATA` and `ENABLE_OPENBB_SERVER` default false.

See `docs/phase-6-plan.md` for scope and verification requirements.

### Phase 7 — SEO, crawlability and discovery

Starter sitemap/robots/llms and other artifacts exist, but the hosting-dependent acceptance (HTTPS, link/crawl checks, canonical/meta coverage, performance, slug redirects, backlink verification) is not verified. Historical artifact authorization is not deployment authorization. See `docs/phase-7-plan.md`.

### Phase 8 — External-service integration

Plan-only, with no current build/deployment authorization. Vendor integrations require Phase 7 production acceptance, vendor-specific security/legal review, and their own explicit approvals. Phase 5's blocked live/broker-related gates remain applicable to payment or account linkage. See `docs/phase-8-plan.md`.

### Phase 9 — AI/agent interface and production hardening

Historical build-transition text does not constitute current authorization. Agent/MCP capabilities remain planned, disabled by default, and subject to human-in-the-loop and data-scope controls. Phase 5 remains blocked; see `docs/phase-9-plan.md`.

## Design direction: Linear-inspired, Gateway-specific

Use Linear as a reference for clarity, speed and restrained visual hierarchy—not as a trading-terminal template to copy.

### Visual principles

- **Quiet dark precision:** near-black canvas, layered charcoal panels, soft white text and hairline borders. Use one bright accent for the single primary action in a view.
- **Information over decoration:** no glowing charts, rainbow controls or competing filled buttons. Colour communicates market direction, risk and status only.
- **Dense but breathable:** compact rows and data tables, with generous blank space around the active chart, strategy or report.
- **Product-native surfaces:** chart, scanner, run report, event detail and order review are the visual material—not hero illustrations.
- **Keyboard-first speed:** command palette, predictable shortcuts, quick symbol switcher and focused inspector views.

### Target workspace

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Gateway   ⌘K Search markets, strategies and commands        Paper ▾  User │
├───────────────┬───────────────────────────────────┬──────────────────────┤
│ Workspace     │ EURUSD · 1h                       │ Decision inspector   │
│ • Overview    │ [Chart + indicators + event marks]│ Price / change       │
│ • Scanner     │                                   │ Next macro events    │
│ • Watchlists  ├───────────────────────────────────┤ Signals & confidence │
│               │ Research | Strategy | Backtest    │ Paper order preview  │
│ My work       │ Clear evidence panels for the     │ Risk / provenance    │
│ • Strategies  │ selected tab                      │                      │
│ • Backtests   │                                   │                      │
│ • Journal     │                                   │                      │
└───────────────┴───────────────────────────────────┴──────────────────────┘
```

### Immediate screen changes from the supplied screenshots

1. Replace the broad top navigation and separate pages with the persistent shell above.
2. Remove raw scraped/news payloads completely. Show source, timestamp, impact, affected currency/instrument and a readable summary.
3. Move strategy generation out of the bottom of the chart into a dedicated **Strategy** tab with a reviewable rule summary and explicit “Run paper backtest” primary action.
4. Change the order panel into a contextual inspector that starts in **Paper** mode and shows risk checks before an order can be submitted.
5. Turn the empty chart region into a finished chart state: price, session, selected timeframe, indicators, event markers, loading/no-data state and a small source/freshness label.

## Prioritisation guardrails

- Do not build broad asset coverage before the data model, entitlements and freshness controls work for one narrow initial market.
- Do not market AI forecasts or generated strategies as trade recommendations. Present assumptions, uncertainty and validation status.
- Do not add live execution until paper reconciliation and loss-control mechanisms are proved, with independent settled broker evidence.
- Keep simulated portfolio records, broker-order intents and broker-origin fills as distinct facts and stores.
- Any future broker order submission requires durable intent persistence/recovery before POST and exact paper-origin host enforcement; never retry ambiguous POSTs blindly.
- Prefer provider adapters and portable schemas to direct UI-to-vendor coupling.
- Every strategy result must record its data version, time window, costs, execution assumptions and model/engine version.

## Follow-up: CSV security remediation

The attached 2026-10-18 security findings are triaged in [`security findings remediation design`](superpowers/specs/2026-10-18-security-findings-remediation-design.md). Follow-up designs cover [`account ownership`](superpowers/specs/2026-10-18-account-ownership-isolation-design.md), [`paper risk admission`](superpowers/specs/2026-10-18-paper-risk-admission-design.md), [`API and input hardening`](superpowers/specs/2026-10-18-api-input-hardening-design.md), and the separately gated [`broker-fill reconciliation evidence flow`](superpowers/specs/2026-10-18-broker-fill-reconciliation-design.md). These are review artifacts, not implementation authorization.
