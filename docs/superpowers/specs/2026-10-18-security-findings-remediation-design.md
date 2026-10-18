# Security Findings Remediation — Design Index

**Date:** 2026-10-18  
**Status:** Draft for user review; this index and its linked designs do not authorize code changes by themselves.  
**Input:** `/Users/ChristineC/Downloads/Acheron449-agent-findings.csv` (24 rows; repository-local findings).  
**Workspace:** `Acheron449/Gateway`; review was against the current working tree, not the scan's older revision.

## Goal and accepted boundary

Resolve the findings that still reproduce in the current checkout without weakening the prior paper-only protections or assigning shared historical data to a user by guesswork. The user selected **per-user isolation**. New private records and simulated portfolios will be scoped to the verified `CurrentUser.id`; pre-existing records with no recorded owner remain unowned and inaccessible through ordinary user routes until a separately reviewed migration assigns ownership. Global administrative actions (shared risk configuration, global kill switch and shared provider configuration) require a configured operator allowlist and fail closed when none is configured. Live broker order submission stays unavailable.

Success means each confirmed item has a root-cause fix and regression test, existing fail-closed execution behavior remains covered, account ownership is derived from the verified principal (not request data), and runtime/resource limits are tested at the shared boundary. Reconciliation evidence remains separate from simulated fills and cannot be declared complete from fixtures.

## Design split

These are independent subsystems; each needs its own implementation plan after the user reviews and approves the written designs.

1. [Account ownership and private-data isolation](2026-10-18-account-ownership-isolation-design.md) — vault, journal, strategies, paper portfolio and AI settings/memory.
2. [Paper risk admission and state consistency](2026-10-18-paper-risk-admission-design.md) — shared order admission, authoritative kill switch, blackout enforcement, valuation, reservations and bounded fill processing.
3. [API and hostile-input hardening](2026-10-18-api-input-hardening-design.md) — Auth0 audience, provider credentials/origins, quote errors, Kronos installation/candles, Markdown and chat limits.
4. [Broker-fill ingestion and reconciliation evidence](2026-10-18-broker-fill-reconciliation-design.md) — next separately gated evidence subsystem, independent of the simulator ledger.

## CSV triage against current code

“Confirmed” means the vulnerable behavior was present in the source read during this review. “Already contained” means the reported public path is currently unavailable or the relevant dependency is already mandatory; it still receives a regression guard, not a claim that the broader architecture is complete.

| CSV row | Current assessment | Design / disposition |
|---:|---|---|
| 1 | **Confirmed.** `risk_engine.py` imports nonexistent `app.services.calendar`, calls an async service as sync, accesses dictionary fields on model objects, and suppresses all exceptions. | Risk admission design: use a valid calendar-service contract and fail closed when coverage is unavailable. |
| 2 | **Confirmed.** AI paper execution calls `PaperPortfolioService.submit_order` and acknowledges directly, without shared risk admission. | Risk admission design: every paper submitter uses one service before persistence. |
| 3 | **Confirmed.** AI chat sessions use one browser-wide localStorage key and restore without owner checks; auth logout does not clear it. | Ownership design: namespace by verified user and clear on identity transitions/logout. |
| 4 | **Confirmed.** Dashboard `risk_config.kill_switch_active` and the engine's process-local boolean are independent. | Risk admission design: one durable authoritative state used by dashboard and all admissions. |
| 5 | **Confirmed.** Vault routes require authentication, but the encrypted store is globally keyed by secret name without ownership. | Ownership design: user namespace, with old unowned entries quarantined. |
| 6 | **Confirmed.** Journal create/list/read/update/delete and `/sync-live` have no user dependency; automated memory aggregates any closed row. | Ownership design: owner-scoped journal; memory excludes user-entered records and accepts only provenance-backed simulator or broker fills. Broker import remains blocked until its own evidence path is approved. |
| 7 | **Confirmed.** Runtime Kronos installer is reachable through a router with optional authentication and starts a shell script that mutates the running Python environment. | Input-hardening design: installation disabled by default and operator-gated if retained; prefer deployment-time installation. |
| 8 | **Already contained at the public application boundary.** `/live` is not mounted; no reachable public handler currently bypasses the live halt. | Preserve route-unmounted regression coverage; do not reopen it as part of this work. |
| 9 | **Confirmed.** AllTick exception text can contain its credential-bearing request URL, and the quote API returns `str(exc)`. | Input-hardening design: fixed public failure messages and status-only safe metadata. |
| 10 | **Confirmed.** The portfolio stream calls a simulator method per order; every call reloads and scans all open orders. | Risk admission design: pass the already-loaded order through and bound/batch processing. |
| 11 | **Confirmed.** Authenticated provider updates can override a `base_url_editable=false` destination; resolver can combine a caller-selected origin with an existing shared secret. | Input-hardening design: operator-gate shared configuration; enforce catalogue origin policy and bind keys to approved origins. |
| 12 | **Confirmed.** Inline link matching rescans unmatched bracket text with an unbounded regex; response size/stream accumulation has no aggregate cap. | Input-hardening design: linear tokenizer, bounded Markdown rendering and aggregate stream cap. |
| 13 | **Confirmed.** `bars_to_kronos_frame` constructs a DataFrame from all caller keys before filtering; there is no count cap at the shared converter. | Input-hardening design: validate allowlisted candle keys/count before DataFrame allocation. |
| 14 | **Already contained for current public access.** The live router is not mounted, and `AlpacaLiveProvider.place_order` fails closed pending durable intent/recovery. | Keep both guards and add non-regression tests; no broker calls. Cancellation remains inaccessible through the unmounted router. |
| 15 | **Confirmed.** Risk checks value an order using `limit_price` even for MARKET/STOP types, while actual simulated fill terms can differ. | Risk admission design: order-type-aware conservative valuation and actual-fill validation in the transaction. |
| 16 | **Already contained for public routing.** The live router remains unmounted; `get_current_user_optional` on a router would not qualify as authorization if it were mounted. | Preserve no-mount regression; implementation must not re-enable it. |
| 17 | **Confirmed.** New accepted orders do not reserve buying power/exposure and later fills do not atomically re-check aggregate risk. | Risk admission design: atomic admission/reservation and fill-time constraint validation/release. |
| 18 | **Dormant while live routes are unmounted.** The live limits handler returns a temporary object and ignores it, but is not currently a reachable public route. | Keep route unmounted. Any future live API must persist/effectively enforce limits in a separately approved design. |
| 19 | **Already fixed in current code.** `POST /llm/chat` now requires `CurrentUser` before returning the stream. | Preserve an unauthenticated-request 401 regression test; aggregate cost/input limits are addressed separately in input-hardening design. |
| 20 | **Confirmed.** HTTP portfolio handlers select a fixed shared portfolio and lack authentication/ownership checks. | Ownership design: owner-scoped portfolios/routes; legacy shared portfolio is quarantined. |
| 21 | **Confirmed.** Strategy and dashboard-risk mutation handlers are unauthenticated; shared risk changes also need operator authorization. | Ownership design: strategy ownership; risk configuration and global halt use configured operator allowlist. |
| 22 | **Already contained.** Live order routes are unmounted and provider placement fails closed; paper-only mode is enforced in settings. | Preserve static/runtime tests and do not add any route that exposes provider mutation. |
| 23 | **Confirmed.** Projected short exposure is clamped and does not use the absolute signed post-order position consistently. | Risk admission design: compute projected signed position and absolute exposure, including long/short crossings. |
| 24 | **Confirmed.** Auth0 audience verification is deliberately disabled when `AUTH0_AUDIENCE` is absent. | Input-hardening design: require audience when Auth0 is enabled and always verify it. |

## Global constraints

- Execution remains paper-only; no broker endpoint calls, order placement/cancellation, or credentials are permitted in implementation tests.
- Simulated fills, broker intents/order states, and broker-origin fills remain different facts and stores.
- Never assign legacy unowned journal/vault/portfolio records to the first authenticated user or to an assumed operator.
- Operator authorization is environment-configured by verified user IDs; an absent/empty allowlist denies the administrative action.
- Keep `ROADMAP.md`'s existing ignore rule unchanged; use a tracked copy at [`docs/gateway-roadmap.md`](../../gateway-roadmap.md).
- No deployment, commit, push, or external service provisioning.

## Review and implementation gates

The user approved the in-chat architecture, authorizing these written designs and an implementation plan only. This draft is now submitted for review. After written-design approval, prepare a separate, testable plan for each independent subproject; request plan approval before changing product code. The broker-fill reconciliation design remains separately gated: its document does not authorize ingestion, broker access, or any soak/trading activity.
