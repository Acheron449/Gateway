# Paper Risk Admission and State Consistency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Execute task-by-task only after the user approves this plan. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Require one durable, owner-aware, atomic admission and fill-validation path for every simulated paper order, with conservative closed-market queue semantics and portfolio-level short controls.

**Architecture:** Build on approved API exposure stopgap, Foundations Task 0 (transaction, clock, versioned migration, append-only audit), and principal/portfolio ownership. Implement one `PaperOrderAdmissionService` for quote/calendar inputs, conservative valuation, reservations, and persistence. Validate fills transactionally and bound streaming work. Broker/live paths stay unavailable and broker-origin facts remain outside this ledger. Use the already-installed Alpaca Trading API calendar as the verified regular-session source; it is a credentialed read-only calendar call and closed-market queueing fails closed if its credentials, response, or published coverage are unavailable.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, SQLite, installed `alpaca-py` read-only calendar client, existing `EconomicEvent` / calendar service, pandas only where already used, pytest/httpx/asyncio. No new service or dependency.

**Spec:** [Paper Risk Admission and State Consistency](../specs/2026-10-18-paper-risk-admission-design.md); merged decisions: [Merged Implementation Plan](../specs/2026-10-18-merged-implementation-plan.md)

## Global Constraints

- Requires the API/input-hardening exposure stopgap, Foundations Task 0, owner-qualified identities, and per-owner portfolios; never use `paper_default` or `default_user` for SaaS users.
- Every order is paper-only. No broker requests, credentials, order placement/cancellation, or live route mount. Simulator fills and broker-origin fills remain different stores.
- `PaperOrderAdmissionService.submit_order(owner_id: str, portfolio_id: str, order: Order, market_context: MarketContext) -> AdmissionResult` is the sole accepted-order boundary; no caller acknowledges before its commit.
- Closed-market market order: queue against latest eligible close with a **2% adverse price collar**, reserve collar notional, execute only in the next verified regular session while within collar, and expire unfilled at that session's close. Use Alpaca's credentialed read-only Trading API calendar—not weekday arithmetic or the economic-event calendar. Call only the calendar GET, never account/order methods, and assert complete coverage within Alpaca's published 1970–2029 bounds. Missing credentials, API/schema failure, incomplete coverage, or a date outside bounds makes closed-market orders unavailable. Distinguish a covered non-session from missing/failed coverage.
- Simulated short: require operator-managed `SHORTABLE_SYMBOLS` allowlist membership and explicit `borrow_eligible[symbol] is True`; require settled owner cash before admission equal to **100% of short notional in additional collateral**, segregate the short-sale proceeds so they cannot fund buys/withdrawals, and reserve both amounts until cover/cancel release. No borrowing, margin extension, or use of short proceeds as buying power. Apply max per-symbol short notional/concentration, gross/net exposure, 2% session-opening-equity per-position loss, and 5% session-opening-equity daily-loss limits; unknown/missing input denies. This is simulation policy, not broker borrow proof, and does not permit live shorts.
- Global config and shortable-symbol allowlist changes require `GATEWAY_OPERATOR_USER_IDS` as strict JSON array of `{issuer,subject}` pairs; missing, empty, malformed, or duplicate/ambiguous entries deny. This exact identity-pair representation is used across the authentication/ownership plans; never use raw `user.id` alone or opaque `principal_id` in this env config. Users may halt their own portfolio; only operator may resume shared/global halt. Automated risk triggers may halt.
- Fail closed on active/unreadable kill state, missing policy input, unavailable/malformed required blackout data, missing/stale/delayed quote, unbounded price, transaction conflict, or violated actual-fill invariant. Quote freshness is measured from the provider/exchange timestamp, never fetch time; accept only non-delayed feeds whose timestamp is at most 15 seconds old. Yahoo and other delayed feeds are ineligible for order valuation regardless of a recent fetch timestamp. Weekday-only arithmetic is never a session source; use the installed Alpaca calendar with explicit coverage/availability validation.
- Tests make no external provider/broker calls; inject quote/calendar/clock. Calendar contract tests use recorded/synthetic local fixtures only. No deployment, commit, or push.

## Review Focus

- An event exactly at blackout boundary, immediately before/after, with timezone-naive timestamp or malformed source status must be decided by explicit symmetric UTC semantics and fail closed when coverage is untrusted.
- Market/stop requests with irrelevant price fields, stale/missing quotes, or conservative slippage beyond the collar are rejected/held without acceptance or fill.
- Concurrent pending orders and partial fills cannot overdraw capacity; reservations are consumed/released exactly once for fill, cancel and expiry.
- Short orders that reduce an existing long, cross zero, open an allowlisted short, or target a nonallowlisted symbol must compute signed projected exposure correctly; absent borrow eligibility always denies new short exposure.
- Kill activation and fill transaction failures cannot report success or leave ledger/event/reservation state partially committed.

---

## File Map

- Modify `quant-app-v1/backend/app/services/database.py`: use Foundations Task 0 transaction/migration/audit helpers and owner-scoped reads/writes; add versioned paper-risk, reservation, and policy tables using append-only audit events.
- Create `quant-app-v1/backend/app/services/paper_order_admission.py`: typed immutable market context, policy snapshot, valuation, admission result/rejection, idempotency, and the single manual/AI order boundary.
- Modify `app/services/risk_engine.py`, `app/api/v1/risk.py`, `app/api/v1/portfolio.py`, `app/services/paper_portfolio.py`, `app/services/fill_simulator.py`, `app/services/ai_trading.py`, and `app/api/v1/ai_trading.py`.
- Modify `app/services/fill_simulator.py` and add `app/services/session_calendar.py`: expose `get_sessions(start: date, end: date) -> list[MarketSession]` using `TradingClient.get_calendar(GetCalendarRequest(start=..., end=...))`, with exact timezone-aware `open_at`/`close_at`, explicit `covered_start`/`covered_end`, source and fetched timestamp. Validate schema/date completeness, published 1970–2029 range, and distinguish covered non-session from missing/failed coverage. Provide test injection; never call account/order APIs. Use actual early closes; no new dependency.
- Modify `quant-app-v1/frontend/src/components/features/PaperTrading.tsx` and frontend paper-trading E2E: stable per-ticket idempotency key survives network retries and rotates only for a new/changed order intent; authenticated unavailable state keeps Trade visibly disabled until ownership and risk admission ship together.
- Tests: add `tests/test_paper_order_admission.py`, `tests/test_paper_order_reservations.py`, `tests/test_paper_risk_calendar.py`, `tests/test_paper_fill_invariants.py`; create `app/services/session_calendar.py` and `tests/test_session_calendar.py`; extend `tests/test_phase4_paper_portfolio.py` and frontend E2E paper trading coverage.

## Task 1: Typed policy, market context and admission result contracts

**Files:** Create `app/services/paper_order_admission.py`; modify `app/models/__init__.py` only if Order validation needs strict type-specific checks; Test: `tests/test_paper_order_admission.py`.

**Interfaces:**
- `QuoteContext(source_time: datetime, fetched_at: datetime, delay_seconds: int, bid: Decimal | None, ask: Decimal | None, last: Decimal | None, source: str)`; only use `source_time` for freshness, require aware UTC-normalizable timestamp ≤15 seconds old and `delay_seconds == 0`; `fetched_at` is diagnostic, never a freshness substitute. `MarketContext(quote: QuoteContext | None, latest_eligible_close: Decimal | None, market_is_open: bool, next_session: MarketSession | None, calendar_coverage: Literal['available','unavailable','not_required'])`; validate bid ≤ ask and all numeric values finite/positive.
- `AdmissionResult(order: Order, status: OrderStatus, policy_version: int, valuation_basis: str, reservation_id: str, collar_price: Decimal | None)`; `AdmissionRejected(check: str, public_message: str, retryable: bool = False)`.
- `PaperOrderAdmissionService.submit_order(owner_id: str, portfolio_id: str, order: Order, market_context: MarketContext) -> AdmissionResult`.
- Validate LIMIT has `limit_price`; STOP has `stop_price`; irrelevant price fields are rejected; MARKET has neither client-set execution price. Finite positive quantities/prices only. Every order command carries `idempotency_key: str` generated by the frontend once for a ticket intent; retries reuse it.

- [ ] Write named contract tests `test_order_price_fields_are_type_specific`, `test_market_context_requires_fresh_quote_or_eligible_close`, `test_admission_result_records_policy_and_valuation_basis`.
- [ ] Run the targeted tests red using backend test command.
- [ ] Implement types and validators without changing low-level paper storage behavior; do not permit broker order types.
- [ ] Rerun targeted tests and canonical order tests.

## Task 2: Durable policy, kill state, and operator shortability configuration

**Files:** Modify `app/services/database.py`, `app/api/v1/risk.py`, `app/services/risk_engine.py`, `app/services/session_calendar.py`; Test: `tests/test_paper_order_admission.py`, `tests/test_account_ownership.py`, `tests/test_session_calendar.py`.

**Interfaces:**
- Persist one global policy row with `policy_version`, `kill_switch_active`, `reason`, `actor_principal_id`, `updated_at`; persist per-owner halt rows and session-opening equity/position marks. Write immutable changes to Foundations Task 0's append-only audit table in the same transaction. First-run seeding distinguishes no row (initialize safe default under controlled transaction) from unreadable DB (deny); active row must commit before success response.
- `load_risk_policy() -> RiskPolicy`, `update_risk_policy(actor_id: str, patch: RiskPolicyPatch) -> RiskPolicy`, `activate_halt(actor_id: str, scope: Literal['global'] | owner, reason: str) -> HaltState`, `resume_global_halt(actor_id: str) -> HaltState`. Defaults: max single position/short notional 10% equity, gross exposure 200% equity, net exposure 100% equity, per-position session realized+unrealized loss 2% of session-opening equity, daily realized+unrealized loss 5% of session-opening equity; no borrowed buying power. For each short position, collateral is additional unencumbered cash equal to 100% of short notional and proceeds remain separately restricted. Limits are versioned and tighten-only absent a new decision. Gross exposure at 200% is an upper safety ceiling, not buying power or permission to borrow; practical buying power is strictly settled free cash after all buy reservations and separate short collateral. The collateral rule may make actual gross exposure substantially lower. Never net restricted proceeds into new positions. Store settled cash, restricted collateral, and restricted proceeds as distinct buckets.
- `SHORTABLE_SYMBOLS` is an operator-managed JSON object mapping normalized supported symbols to explicit booleans; only explicit `true` plus explicit `borrow_eligible[symbol] is True` is eligible, absent/false/malformed values deny. Parse once and expose read-only; changes require deployment operator configuration/restart. Before accepting a short, reserve separately (a) proceeds equal to short notional and (b) owner settled cash collateral equal to 100% of that notional; neither is buying power, both release only when covered or canceled. This is simulation eligibility, not broker borrow proof. Persist the policy version/snapshot.
- Any authenticated user may halt only their owned portfolio; an operator may activate global halt and resume; automated daily-loss/drawdown triggers can activate an audited per-owner halt. Define automatic halt triggers as session loss ≥5%, per-position session loss ≥2%, or peak-to-trough drawdown ≥5% of opening equity. Cancel is always permitted including during global halt, and atomically releases remaining reservation. Strictly risk-reducing close orders may bypass a per-owner halt only, never a global halt; they cannot cross zero or increase absolute exposure and still require an eligible quote. Missing/stale/delayed position mark triggers owner halt and blocks new exposure; retain last trusted mark for audit. A close needs fresh eligible price data for bounded execution. Automatic triggers operate on per-position marks from last trusted eligible source-time quotes, refreshed once per risk evaluation; persist source timestamp and price. If any held position lacks valid mark, halt the owner and block new exposure until fresh eligible quote; never use fetch time or value missing positions at zero.

- [ ] Add migration tests for fresh DB, pre-existing risk row, missing row, interrupted initialization and unreadable DB; add operator/user permission tests. Add short cash-segregation invariants (sale proceeds cannot fund buys or withdrawals) and precision/concurrency tests.
- [ ] Write `test_kill_switch_persists_across_engine_reinstantiation`, `test_database_failure_never_reports_successful_halt`, `test_short_allowlist_is_operator_only_and_fail_closed`.
- [ ] Verify tests red; implement row/audit schema using transaction helper and inject policy into engine (remove process-local kill as authoritative source).
- [ ] Rerun tests; prove shared halt controls manual+AI through one state and operator unset denies global mutation.

## Task 3: Correct blackout and conservative risk valuation

**Files:** Modify `app/services/risk_engine.py`, `app/services/calendar_service.py` only for typed semantics, `app/services/paper_order_admission.py`; Test: `tests/test_paper_risk_calendar.py`, `tests/test_paper_order_admission.py`.

**Interfaces:**
- `async def check_event_blackout(*, now: datetime, blackout_minutes: int, calendar_events: Sequence[EconomicEvent], coverage: CalendarCoverage) -> list[RiskViolation]`; caller obtains coverage with `await calendar_service.get_economic_events(...)`, which must expose a successful/unavailable state separately from an empty event list; inspect typed `EconomicEvent.importance`, `.scheduled_at`, `.title`. Only high-impact events trigger the configured blackout.
- Blackout interval is `abs(event_time - now) <= configured_minutes`; event times normalize to UTC, provider naive times follow existing adapter policy. With configured positive blackout, unavailable/unconfigured/malformed coverage denies; a successful empty covered response is distinct from unavailable.
- `value_order(order: Order, portfolio: PortfolioSnapshot, market_context: MarketContext, policy: RiskPolicy) -> OrderValuation`; MARKET uses fresh conservative quote bound, STOP uses stop trigger plus conservative slippage, LIMIT uses limit; missing safe valuation denies.
- Project signed target quantity and apply position crossing before absolute per-symbol, gross and net exposure. Do not treat every sell as new short risk. A strictly risk-reducing transition may bypass new-risk caps and an owner-scoped halt, but not a global halt, quote/valuation requirements, collateral release rules, or transactional invariants; it cannot increase absolute exposure or cross through zero. Compare each new short's proceeds and separate cash collateral against its distinct restricted buckets.

- [ ] Add tests for async service call/model event, before/at/after boundaries, valid empty coverage, unavailable/malformed coverage, each order type, signed long close/cross-zero/short, and stale/unknown market data.
- [ ] Run focused tests red against current engine's sync/malformed calendar check and `limit_price` use.
- [ ] Implement typed async blackout and a single valuation object reused for cash, reservation, concentration, gross/net and short limits. Include policy version/basis in the result.
- [ ] Rerun focused tests and existing calendar/risk tests.

## Task 4: Atomic reservations and closed-market market-order collar

**Files:** Modify `app/services/database.py`, create/modify `app/services/paper_order_admission.py`, modify `app/services/paper_portfolio.py`; Test: `tests/test_paper_order_reservations.py`, `tests/test_paper_order_admission.py`.

**Interfaces:**
- In one SQLite connection's `BEGIN IMMEDIATE` transaction from Foundations Task 0 (never call helpers that open/commit another connection inside it), reload owner portfolio, global/per-user halt, risk policy, positions, and accepted/partially filled remaining commitments; calculate new risk and reservation, then commit order, `OrderSubmitted`/`OrderAcknowledged` events, append-only audit event, and acceptance atomically. Provide connection-taking internal DB primitives for this transaction; avoid nested `init_db()` calls.
- `paper_order_reservations` identifies owner/portfolio/order, remaining quantity, reserved cash/notional/collateral/short proceeds, price basis/collar, policy version, status and timestamps. Add `idempotency_key` to the manual/AI order command; unique `(owner_principal_id, idempotency_key)`, duplicate returns prior result without a second order. Legacy order rows have no owner/idempotency and are not rewritten. Sell orders reserve available position quantity as well as notional; pending sells cannot collectively exceed owned quantity.
- Closed-market market orders use `latest_eligible_close` `C`; buy upper collar `C * 1.02`, sell lower collar `C * 0.98`. Reserve quantity × adverse collar plus commission. Execute only in the next session returned by the verified Alpaca calendar; cancel/expire unfilled balance at that session's actual close including early-close times; never carry later. If credentials are absent, requested dates are outside 1970–2029, dates/schema are incomplete, or endpoint is unavailable, deny. Never infer holidays from weekdays.
- At session open, simulate only while current time is within the declared next regular session. Compare final adverse-side simulated price (buy fill ≤ collar upper, sell fill ≥ collar lower); outside collar does not fill and remains pending only until that same session close, then expires. Limit orders retain user price semantics and are not converted into queued market orders. Cancellations are not blocked by global or owner halt and release all remaining cash, quantity, proceeds, and collateral reservation exactly once.

- [ ] Add `test_two_orders_combined_reservations_cannot_exceed_capacity`, `test_concurrent_submissions_serialize`, `test_owner_idempotency_key_returns_one_order`, `test_two_pending_sells_cannot_oversell_position`, `test_cash_collateral_and_restricted_short_proceeds`, `test_closed_market_buy_sell_2_percent_collar_and_reservation`, `test_queued_order_only_next_session_then_expires`, and `test_no_quote_or_close_denies_closed_market_order`.
- [ ] Run tests red against direct submit and no reservation model.
- [ ] Implement admission transaction, owner-scoped cash/position/collateral reservation storage, per-owner short proceeds segregation, and next-session/collar calculation using the injected Alpaca calendar adapter; unavailable calendar coverage fails closed for closed-market orders.
- [ ] Rerun tests and SQLite concurrency tests; assert failed admissions create no order, event, ack or reservation.

## Task 5: Route all manual and AI orders through admission

**Files:** Modify `app/api/v1/portfolio.py`, `app/services/ai_trading.py`, `app/api/v1/ai_trading.py`, `frontend/src/components/features/PaperTrading.tsx`; Test: `tests/test_paper_order_admission.py`, `tests/test_ai_trading_ownership.py`, route tests, `frontend/e2e/paper-risk-admission.spec.ts`.

**Interfaces:**
- HTTP and AI call the same exact `PaperOrderAdmissionService.submit_order(owner_id, portfolio_id, order, market_context)`; fetch quote/calendar before transaction, reload policy/halt/positions inside transaction.
- The storage primitive `PaperPortfolioService.submit_order` is only used by admission. Automated AI cannot persist/ack/fill directly. UI success reflects committed `AdmissionResult`; public rejection responses contain safe check and message.
- Per-user API/provider rate limits are defense-in-depth and keyed to verified principal; they do not replace portfolio caps. Existing global IP limiter remains additional. Frontend order ticket generates a cryptographically random idempotency key for a new intent, retains it across timeout/retry, and rotates it only when a new order ticket is created or any intent field changes. AI signal idempotency is deterministic over owner, strategy, symbol, action and evaluation interval. A non-admitted duplicate returns the prior committed result only; a rejected command may be retried with same key after transient pre-transaction failure, but not after intent changes.

- [ ] Write tests asserting manual and AI entrypoints deny before persistence on halt, blackout, missing/stale/delayed valuation, short-allowlist, insufficient collateral and reservation failure; assert both use the same service. Add a route test that cancellation is allowed under global/per-owner halt and releases reservation only once; add frontend E2E that retries a timed-out ticket with the same idempotency key and changes key on intent edits.
- [ ] Verify red; implement adapter calls, rate-limit identity key and safe HTTP mapping.
- [ ] Rerun tests; test status response only after transaction commit.

## Task 6: Automatic halt triggers and held-position valuation

**Files:** Modify `app/services/risk_engine.py`, `app/services/paper_order_admission.py`, `app/services/database.py`, and risk dashboard responses as required; Test: `tests/test_paper_risk_calendar.py`, `tests/test_paper_order_admission.py`.

**Interfaces:**
- `evaluate_automatic_halts(owner_id: str, *, session_open_equity: Decimal, positions: Sequence[Position], quotes: Mapping[str, QuoteContext], now: datetime) -> list[HaltTrigger]` updates durable per-owner halt state in the same transaction as append-only audit. Trigger on session realized+unrealized loss >= 5% equity, per-position session loss >= 2% equity, or peak-to-trough portfolio drawdown >= 5% threshold.
- At regular-session open, snapshot session-opening equity and per-position unrealized-PnL baselines. Revalue using non-delayed source timestamp quotes (≤15 sec). Keep `last_trusted_price` and source timestamp; if any held symbol lacks a valid mark, preserve last trusted mark for reporting, mark valuation stale, activate owner halt, and block new exposure. Do not fabricate zero or use last fetch time.
- Automatic halt does not disable safety exits: cancels are always permitted, including during global halt, and release reservations atomically. A strictly risk-reducing close may bypass an owner-only halt (not global halt), must close/reduce an existing signed position without crossing through zero, and requires a fresh eligible quote to bound execution; it never bypasses fill/transaction invariants.

- [ ] Test each loss/drawdown threshold just-below/equal/above; opening baselines reset at regular-session open; PnL marks use source timestamps; missing/stale/delayed quotes preserve last trusted mark, set stale valuation, and durably halt without zero substitution.
- [ ] Test cancel under owner/global halt, close/reduce under owner halt, and rejection under global halt, missing quote, or cross-zero request.
- [ ] Run tests red; implement durable marks, trigger and audit update through the shared transaction helper.
- [ ] Rerun risk tests and ensure halt response reflects committed durable state.

## Task 7: Fill-time revalidation, settlement, and bounded streaming

**Files:** Modify `app/services/fill_simulator.py`, `app/services/paper_portfolio.py`, `app/services/database.py`, `app/api/v1/portfolio.py`; Test: `tests/test_paper_fill_invariants.py`, `tests/test_phase4_paper_portfolio.py`.

**Interfaces:**
- Add `try_fill_order_data(portfolio_id: str, order_data: Mapping[str, Any], *, now: datetime | None = None) -> FillResult | None`; keep ID lookup as wrapper. Pass loaded order from WebSocket batch rather than re-read entire portfolio per order.
- For each simulated fill, under one transaction verify reservation, current owner state, fill price/quantity/commission, collar if queued; apply fill/order/position/cash/ledger/event/reservation changes atomically. Use existing deterministic event-derived `fill_id` or a persisted idempotency token to prevent the current generated fill ID from duplicating on retry. Violation sets explicit terminal/held status with audit; no success fill event without committed ledger state.
- Cancellation and expiry release remaining reservation once. Partial fill consumes matched amount and retains only remainder.
- Stream processes a finite oldest-first batch with pacing and asynchronous DB offloading only if needed; heartbeat test ensures event loop remains responsive. No queue/worker service added.

- [ ] Write tests for fill outside collar, actual commission crossing policy, partial-fill reservation consumption, cancel/expiry release, duplicate fill prevention, no partial writes after simulated DB exception, and non-session/early-close expiry from the approved calendar fixture (no external calls).
- [ ] Write N-order stream test asserting bounded portfolio reads and finite oldest-first batch; add heartbeat responsiveness test.
- [ ] Run tests red; implement `try_fill_order_data`, transactional accounting and batch loop.
- [ ] Rerun named tests and existing portfolio simulator regressions.

## Task 8: Final risk regression gate

- [ ] Run `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_paper_order_admission.py tests/test_paper_order_reservations.py tests/test_paper_risk_calendar.py tests/test_paper_fill_invariants.py tests/test_phase4_paper_portfolio.py tests/test_ai_trading_ownership.py tests/test_calendar_sources.py tests/test_session_calendar.py`.
- [ ] Run API-level tests for manual, AI, halt, operator allowlist and owner isolation; run frontend paper-order E2E, build/typecheck if UI touched.
- [ ] Verify no `/live` router or broker adapter call is reachable and no broker network fixture was used; assert no live host literal introduced in execution code.
- [ ] Inspect migration back/forward behavior, transaction boundaries and event/ledger consistency; run `git diff --check`, secret-pattern scan (matched lines suppressed), and record exact commands, results and blockers in the SDD ledger.

## Decisions settled for this plan

- **Calendar source decision:** use Alpaca's existing, credentialed Trading API calendar via `TradingClient.get_calendar(GetCalendarRequest(start=..., end=...))`; it supplies regular market days plus open/close times, including early closures. Request explicit dates, validate coverage/schema, and fail closed outside published 1970–2029 coverage or if credentials/API are unavailable. This is read-only schedule access; no account/order methods and no new dependency. Evidence: [Alpaca Calendar API](https://github.com/alpacahq/alpaca-docs/blob/master/content/api-references/trading-api/calendar.md), [Python SDK calendar reference](https://alpaca.markets/sdks/python/api_reference/trading/calendar.html), [Authentication](https://docs.alpaca.markets/us/docs/authentication).
- **Quote timestamp:** require source/exchange timestamp and non-delayed provider; max age 15 seconds. Fetch time is not a freshness proxy; Yahoo and delayed IEX data are rejected for order admission.
- **Per-position loss cap:** 2% of session-opening equity, tighten-only.
- **Short policy:** permit simulation shorts only when short proceeds are segregated and an additional 100% of short notional is reserved from settled owner cash; no borrowed buying power. Overall exposure limits still apply. The 200% gross cap is only a ceiling; it does not permit borrowing or use of restricted short proceeds. Available cash for buys is settled free cash after buy reservations and separate short collateral.
- **Idempotency/UI:** the frontend creates a cryptographically random key per order-ticket intent, retains it across retries, and rotates on any intent edit or new ticket; add a paper-order E2E assertion. Reuse the original key only for the same payload.
- **Halts:** cancellations are always allowed and release reservations; strictly risk-reducing closes can pass an owner halt only, not a global halt, and require fresh eligible quote data. No crossing through zero. Missing/stale/delayed marks trigger an owner halt and prevent new exposure; retain the last trusted mark for reporting, never zero-substitute.
- **Automatic triggers:** session realized/unrealized loss ≥5%, any position's session loss ≥2%, or peak-to-trough drawdown ≥5% of session-opening equity; at regular-session open snapshot opening equity and each position's unrealized-PnL baseline. Revalue only from eligible non-delayed source-time quotes no older than 15 seconds. Retain each last trusted price/source timestamp; a held position without a fresh mark sets valuation stale and activates an owner halt, never zero-substitute. Cancels always work; fresh-quote, strictly risk-reducing closes may bypass owner halt only, never global halt, and cannot cross zero.

- **Risk-level test/file coverage:** add `test_two_pending_sells_cannot_oversell_position`; Task 6 covers loss triggers/marks/stale-quote halting; Task 5 names frontend ticket retry/same-key and intent-edit/new-key E2E; Task 8 runs `tests/test_session_calendar.py` as well as all named risk tests. No order UI, backend order route, AI submitter, or simulator acceptance is enabled before Ownership Task 4 and Risk Tasks 1–7 ship together; until then show Trade/orders as unavailable with explicit status text.

## Self-review / Dependency Gates

- Dependency order: Hardening Task 0 exposure stopgap plus independent Tasks 1, 2, and 4 first; then shared Foundations Task 0; then Ownership Task 1; then Ownership Tasks 2 and 3 (journal may proceed, BYOK remains gated on separate migration approval/application/deploy); then Ownership Task 4 and Risk Tasks 1–7 together as one coordinated Trade release; Ownership Tasks 5/6 follow, then remaining hardening Tasks 3, 5–7. UI displays explicit Trade/orders unavailable state until owner scoping and admission deploy together. Risk must use Foundations transaction/clock/migration/audit contracts and never create parallel versions.
- Required market data/calendar are injected before admission transaction, then authoritative halt/policy/positions are re-read under transaction. Quote `source_time` controls freshness; fetched time never substitutes. Source delay must equal zero. A successful external quote does not override a newly active kill switch. The Alpaca Trading API calendar uses the already-installed `alpaca-py`; use only the calendar endpoint and validate exact bounds, coverage and early closes.
- Collar is 2% adverse in either order direction around the most recent eligible close; execution only in the next verified Alpaca session, within collar, and expiry at that session's exact close including early closes. No weekday approximation or overnight carry. Missing credentials/coverage fail closed. Tests use fixtures only and no real network.
- Shorting is simulated only with normalized deployment `SHORTABLE_SYMBOLS`, explicit borrow eligibility, segregated sale proceeds plus additional settled cash collateral equal to 100% short notional; no borrowing or reuse of proceeds. Enforce 10% single position/short notional, 200% gross as an upper ceiling (not buying power), 100% net, 2% per-position loss and 5% daily/drawdown caps. Actual buying power is settled free cash less all reservations; no borrowing, and restricted short proceeds cannot fund buys/withdrawals. Unknown/missing input denies new short exposure; risk-reducing close cannot cross zero.
- No broker order-intent or fill-ingestion/reconciliation system is implemented here; durable broker recovery and evidence gate remain separate designs and authorization. A separately approved Alpaca calendar adapter, if selected, is schedule-only and cannot reach account, position, order, cancel, or trade endpoints.
