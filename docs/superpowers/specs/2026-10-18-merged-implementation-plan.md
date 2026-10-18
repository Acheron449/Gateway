# Merged Implementation Plan: Paper Safety, Ownership, Risk, Hardening, As-Of, Reconciliation

**Date:** 2026-10-18
**Status:** Draft for user review. This plan authorizes no code changes. Each phase needs its own task-level plan and approval before implementation.

**Merges:** paper-safety design and plan, account-ownership isolation, API/input hardening, paper risk admission, as-of data filtering, and broker-fill reconciliation (the last remains gated).

Effort key: S = small, M = medium, L = large. Phases run serially for a single implementer.

## Open decisions (answer before Phase 1 task breakdown)

| # | Decision | Options | Answer |
|---|----------|---------|--------|
| 1 | Local commits (no pushes) per phase, so each gate is a real checkpoint | yes / no | No commits; keep work uncommitted in the shared checkout. |
| 2 | Local HS256 tokens and Auth0 together | allow both (issuer-qualified IDs) / mutually exclusive | Allow together; qualify every principal key by verified issuer and subject. Include existing Supabase Auth issuer as a separately verified namespace. |
| 3 | LLM provider key | shared key with per-user limits / bring-your-own key via per-user vault | BYOK now; provider credentials/settings are per-user and encrypted. Operator-managed shared-key mode, with per-user budgets/rate/concurrency limits before any provider call, is a later separately planned addition. |
| 4 | AI-trading background loops | per-owner / operator-only / disabled | Per-user loops scoped to each owner's portfolio and persisted config; never resume a shared legacy loop. |
| 5 | Market orders while the market is closed | reject / queue with reservation at last close plus price collar | Queue with 2% adverse collar around latest eligible close; reserve at collar, execute only in the next regular session within collar, and expire at actual close. Use the existing Alpaca Trading API calendar via installed `alpaca-py`; it is credentialed/read-only and has published 1970–2029 coverage. Missing credentials/coverage fail closed. |
| 6 | Shorting | confirm "not supported" as default | Allow simulated shorts subject to portfolio-level risk gates and an operator-managed shortable-symbol allowlist; add per-user API/provider rate limits. Real broker/live shorting remains unavailable. |
| 7 | Is `broker_service.py` reachable today (orchestrator, `ai_trading.py`)? | yes / no / unknown | No active runtime caller found. `TradingOrchestrator.process_market_data` returns before order creation; BrokerService references are its commented example and tests. Keep its provider placement fail-closed as defense-in-depth. |

## Recorded decisions and scope

The answers above were provided by the user on 2026-10-18 and supersede conflicting text in earlier draft designs. Any implementation plan must preserve these exact policies. LLM shared-operator-key budgeting is explicitly later work. BYOK is the selected model, but enablement is blocked until the separately approved Supabase migration is applied, contract-tested, and deployed with its matching backend; until then LLM chat is unavailable to all users, the old shared operator key stays quarantined with no fallback, and the UI clearly prompts “Add your key” and reports migration/service unavailability. As-of filtering in Phase 5 has already been implemented and verified according to `docs/superpowers/plans/2026-10-18-as-of-data-filtering.md`; do not redo it. Baseline route/host guards and roadmap tracking are also already delivered. The active plans below should focus on unfinished security findings and ownership/risk/API hardening. Broker intent/recovery and real-fill reconciliation remain disabled/gated unless a phase plan explicitly stays fixture-only.

## Rules for every phase

- Tests are written red first, then made green. Compile changed modules, run focused tests, then the broad suite; record real exit codes and known blockers. Typecheck/build the frontend when it is touched.
- Run a read-only secret-pattern scan (suppress matching lines; record file names and counts only) and `git diff --check`. Leave `quant-app-v1/backend/.DS_Store` untouched.
- Phase gate = tests green plus a ledger entry (plus a local commit if decision 1 is yes).
- Execution stays paper-only (`GATEWAY_EXECUTION_MODE=paper`). No test calls a broker. Simulated fills, broker order intents, and broker-origin fills remain three separate stores.
- Status labels: only `implemented`, `verified`, `partially verified`, `blocked`, `not started`. Synthetic fixtures are never real evidence.
- No deployment, push, or external provisioning.

## Phase 0: Baseline (S)

- [ ] Confirm which protections have already landed: `/live` router unmounted, `AlpacaLiveProvider.place_order` fail-closed, host guards. Reconcile the document conflict about whether `live.py` was mounted with optional auth.
- [ ] Decide the fate of `broker_service.py`: it has its own POST path, a substring paper-URL check (`"paper-api.alpaca.markets" in base_url`, bypassable by a crafted host), default redirect following, the status-mapping bug (`canceled`, `partially_filled`, `expired` fall back to pending), and no `client_order_id`. Either consolidate onto one adapter or guard it identically.
- [ ] Inventory every router using `get_current_user_optional` and every unauthenticated mutating route.
- [ ] Create the tracked `docs/gateway-roadmap.md` (keep the existing `ROADMAP.md` ignore rule).
- **Gate:** written baseline report.

## Phase 1: Exposure stopgap (M)

Ship this first, before identity/ownership migration. Authenticate first, scope later; where authentication alone would still expose shared private data, return stable 503 until its owner-scoped task ships.

- [ ] Require verified `CurrentUser` on private portfolio, strategy, risk, journal, vault, provider-settings, and AI-trading handlers; anonymous requests receive 401 before any side effect. Global/current shared-store controls are operator-only or stable 503, never merely login-gated. Journal `/sync-live` is unavailable.
- [ ] Use `GATEWAY_OPERATOR_USER_IDS` as a strict JSON array of exact verified `{issuer,subject}` objects; absent/empty/malformed denies. This representation remains unchanged after opaque principal mapping.
- [ ] Auth0: require nonempty `AUTH0_AUDIENCE` when enabled and always verify audience, issuer, algorithm, signature, expiry, and not-before.
- [ ] AllTick errors/logs and public quote failures expose fixed messages/status only, never tokenized URL/query/response text.
- [ ] Against the current provider store (without waiting for BYOK RPC migration): reject immutable-catalog URL overrides and ignore stored overrides; gate all global market-data provider routes with the strict operator check; bind credentials to approved origins, require fresh key on origin change, and disable redirects. Immediately revalidate DNS before connect and document the remaining DNS-rebinding race if httpx pinning is infeasible.
- [ ] Kronos runtime installer defaults disabled; an explicit disabled state is safe without identity work.
- [ ] Enforce exact paper host, HTTPS and no redirects in each broker-execution request path.
- **Gate:** anonymous and non-operator route matrices pass; no unauthenticated side effects, credential forwarding, or unsafe live execution host.

## Phase 2: Shared foundations (M)

This work is Ownership Plan Task 0 and has a named owner/test suite; ownership identity migration and risk storage depend on it.

- [ ] Implement one SQLite `BEGIN IMMEDIATE` transaction/context helper with per-operation connections and a retryable `TransactionConflict`; prove serialization and bounded lock failure with two real on-disk SQLite connections/threads.
- [ ] Implement injectable aware UTC clock and deterministic expiry boundary tests.
- [ ] Implement ordered, versioned additive migrations with atomic schema/version commit and NULL-owner quarantine; test failed DDL/partial migrations and rerun.
- [ ] Implement append-only structured audit table and reject updates/deletes at DB boundary; append state change + audit in one transaction.
- **Gate:** real-connection concurrency, rollback, clock, migration atomicity, and audit immutability tests pass.

## Phase 3: Ownership isolation (L)

Starts only after Phase 1 and the explicit Phase 2 foundations task.

- [ ] Task 1 maps verified `(issuer,subject)` to opaque principal IDs and applies strict operator checks; preserve local raw subject for profile/login/refresh compatibility.
- [ ] Tasks 2/3 isolate vault/provider BYOK, journal, and memory. Journal may proceed without the BYOK migration. BYOK specifically waits for deployed RPC inspection, separate migration approval, migration application, contract tests, and matching backend deployment; until all complete, chat stays unavailable, the shared key remains quarantined, and provider/chat UI communicates “Add your key” plus the migration/service-unavailable state.
- [ ] Task 4 scopes strategies and paper portfolios. Preserve legacy ownerless/duplicate rows without auto-assignment; use partial unique owner index `UNIQUE(user_id) WHERE user_id IS NOT NULL` only once `user_id` is confirmed to store principal IDs. Ship with Phase 4 Risk Tasks 1–7 as one release; until then the server order path and Trade UI both state orders are unavailable.
- [ ] Tasks 5/6 scope AI-trading lifecycle and isolate frontend chat on identity changes. Task 7 sweeps every raw `user.id`/`CurrentUser.id`/local-subject assumption and runs compatibility tests.
- [ ] WebSockets authenticate in the first message (not a query-string token) and close at token expiry. All legacy ownerless records remain quarantined.
- **Gate:** two-user matrix for every private resource; foreign/ownerless IDs return 404; opaque-ID sweep and local auth compatibility pass.

## Phase 4: Risk admission (L)

Requires Phase 2 foundations and Phase 3 issuer/portfolio ownership. Ownership Task 4 and this phase are one coordinated Trade rollout, not a window where orders are silently broken or partially enabled.

- [ ] Durable risk/kill state and append-only audit in the shared transaction; authenticated users may halt only their own portfolio, operators control global halt/policy/resume, and automatic triggers can activate owner halt.
- [ ] Fix async economic-event blackout semantics and fail closed on unavailable/malformed coverage.
- [ ] Use type-aware valuation and signed position projections. Shorts remain simulated only with explicit allowlist/borrow eligibility, segregated proceeds, and additional settled owner-cash collateral equal to 100% of short notional. The 200% gross figure is a ceiling, not buying power or borrowing; no borrowed buying power. Keep 10% per-symbol, 100% net, and 5% session loss/drawdown policies.
- [ ] Require non-delayed quotes whose exchange/source timestamp (not fetch time) is no more than 15 seconds old. Reject delayed Yahoo/IEX and any mark without an eligible source timestamp; do not widen the limit based on fetch recency. Quote-based order admission is only useful when a provider supplies eligible source time; otherwise fail closed.
- [ ] Atomic `PaperOrderAdmissionService` handles manual and AI orders, owner idempotency, reservations, and pending sell quantity (including two individually valid sells that together oversell). Closed-market orders use the existing Alpaca calendar with 2% adverse collar, next-session-only execution, and actual close/early-close expiry; missing credentials or verified coverage fail closed.
- [ ] Automatic halt marks: snapshot session-open equity and position PnL baselines; update from trusted eligible source-time marks; retain last trusted mark and timestamp. Missing/stale/delayed mark sets stale valuation and owner halt without zero substitution. Cancels always work under any halt; strictly risk-reducing close orders may bypass owner-only halt, not global halt, require a fresh eligible bound, and cannot cross zero.
- [ ] The frontend generates one stable cryptographically random idempotency key per order-ticket intent; retries reuse it, intent edits/new tickets rotate it. Test through the actual order UI request. Keep Trade explicitly unavailable in UI/backend until Ownership Task 4 and Risk Tasks 1–7 are jointly released.
- [ ] Revalidate simulated fills transactionally and process finite oldest-first batches with event-loop responsiveness; do not move broker-origin fills into this ledger.
- **Gate:** all manual/AI paths use admission; restart, oversell, threshold, stale-mark, safety-exit, and concurrent-capacity tests pass; the coordinated UI/backend order gate is intact.

## Phase 5: As-of data (M)

Independent of Phases 3 and 4 by file, but supplies the clock Phase 4 uses for replay.

- [ ] Admit a bar only when `bar_start + interval <= as_of`; define session and timezone rules and the still-forming-bar policy.
- [ ] Anchor `range` at `as_of`; filter raw rows before and after resampling.
- [ ] Label adjusted-price leakage (tie to `corp_actions`).
- [ ] Include `as_of` in cache keys; handle millisecond timestamps; return "unavailable" beyond provider depth; reject a future `as_of`.
- **Gate:** boundary tests for each provider and resampled path.

## Phase 6: Remaining hardening (M)

Hardening Task 5's shared converter/UI cap may proceed before ownership if identity-independent; remaining work follows each plan's dependencies and can overlap Phases 4/5.

- [ ] Kronos: cap requests to exactly 2,000 bars in UI and backend before DataFrame creation; verify actual forecast requests never serialize more than 2,000 and retain newest bars only. Pin source and model-weight revisions independently; use safetensors or checksum-verified weights-only loading, never unrestricted pickle.
- [ ] Linear Markdown tokenizer and render caps (test operation count, not wall-clock).
- [ ] Aggregate chat/stream bounds, per-owner concurrency cap exactly 2 with atomic release on completion/error/disconnect/cancel, per-user rate limits, and upstream cancellation.
- [ ] Custom endpoint SSRF checks block private/metadata destinations and redirects. Validate DNS immediately before connect and document the remaining rebinding race if the installed httpx path cannot safely pin DNS.
- **Gate:** hostile-input, actual UI request-cap, and concurrent-disconnect tests pass; no unsupported DNS-pinning claim.

## Phase 7: Paper-safety remainder (M)

- [ ] Owner-scoped broker intent store and recovery (only if something can submit broker orders). `RESOLVED` means broker identity known, with broker status tracked separately; only a definitive 404 counts as "not found"; injectable clock for delayed lookups.
- [ ] Comparator and CLI against fixtures: exact `Decimal` matching, completeness metadata, default settle margin, exit codes 0/1/2/3, and boundary tests including `n=999, m=0`.
- [ ] Rename the "live" provider and routes last (highest churn, lowest safety value).
- **Gate:** fixture comparator tests green; synthetic input never yields PASS.

## Phase 8: Docs and evidence (S)

- [ ] Reconcile `ROADMAP.md` (via `docs/gateway-roadmap.md`), phase plans, prerequisites, and `docs/status.md` against code and test output.
- [ ] State that the real evidence gate stays open until Phase 9 completes.

## Phase 9: Future gated work (not authorized here)

- Broker-fill ingestion: read-only real sample first; attribute fills to owners via `client_order_id` to intent to owner with an unattributed bucket; add position and cash checks; name the fill gate an "ingestion consistency gate"; treat Alpaca paper-account resets as new evidence epochs; operator-only until separate accounts exist.
- Opt-in paper soak harness (small caps, rate-limited, kill/stop controls, durable audit).
- Replay sessions (owner-scoped, using the as-of clock in admission).
- Product Phase 4 and Phase 5 evidence gates remain open until then.

## Dependency summary

```
0 Baseline
└─ 1 Exposure stopgap + independent Auth0 / AllTick / current-store endpoint / installer protections
   └─ 2 Shared foundations (owned by Ownership Task 0; real-connection tests)
      └─ 3 Ownership Task 1 (verified issuer+subject -> opaque principal)
         ├─ Ownership Tasks 2/3 (journal independent; BYOK separately migration-gated)
         └─ Ownership Task 4 + Risk Tasks 1–7 (coordinated Trade release; unavailable UI/server before both)
            └─ Ownership Tasks 5/6/7 and dependent remaining hardening
               ├─ 5 As-of (already implemented; supplies clock for future replay)
               ├─ 6 Hardening remainder (including UI/body cap and stream cap)
               └─ 7 Paper-safety remainder
                  └─ 8 Docs
                     └─ 9 Future gated work
```
