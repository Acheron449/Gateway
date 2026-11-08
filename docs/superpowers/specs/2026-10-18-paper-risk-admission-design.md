# Paper Risk Admission and State Consistency

**Date:** 2026-10-18  
**Status:** Draft for user review. No code changes authorized by this design alone.

## Goal

Ensure every simulated paper order is validated against the same effective risk policy before persistence or acknowledgment, with durable kill-switch state and bounded processing. This does not enable broker execution or satisfy broker-fill reconciliation.

## Existing root causes

- `RiskEngine._check_event_blackout` imports nonexistent `app.services.calendar`, treats the async service as synchronous, assumes mapping events instead of `EconomicEvent`, and catches all errors as no violation.
- HTTP portfolio submission calls the engine, but automated `_place_paper_order` directly persists/acknowledges/fills.
- Dashboard `risk_config.kill_switch_active` is distinct from `RiskEngine`'s process-local boolean; engine restart loses it.
- `risk_engine.py` uses `limit_price or current_price` for all order types; a caller can supply irrelevant limit price for MARKET/STOP checks. Concentration clamps short projection to zero. Pending accepted orders are not reserved; simulator fill effects are not checked against aggregate risk.
- Portfolio WebSocket repeatedly calls `try_fill_order`, which loads and scans the whole portfolio for each already-loaded order.

## Design

### Shared admission boundary

Create one `PaperOrderAdmissionService` (or equivalent focused service) with an explicit signature consuming verified owner, owner-scoped portfolio, normalized `Order`, and market context; it obtains the authoritative config/kill switch, evaluates checks, reserves pending capacity atomically, then persists and acknowledges the order. Both `/portfolio/orders` and AI trading call it. The low-level `PaperPortfolioService.submit_order` remains a storage primitive and is not an externally callable acceptance path; callers must not acknowledge before admission succeeds.

If data needed for a configured safety restriction is unavailable, admission fails closed with a clear service-unavailable/rejected result; it never silently treats missing policy input as permission. The paper strategy configuration cannot override server risk restrictions.

### Authoritative risk and kill switch

- Persist a single paper-risk configuration and kill-switch row in SQLite, with schema/version, active state, reason, actor subject, update timestamp and audit event. If no state is available, default to a safe active/deny state until initialized; a DB read/write failure blocks admission.
- Dashboard GET/updates, explicit paper halt/reset, automated runs and HTTP manual order admission use the same service and row. The active state is committed before success is returned.
- Operator authorization for shared global policy/halt is supplied by the ownership design; per-user kill switches may be introduced only with per-user portfolio keys and the same admission transaction.

### Economic-event blackout

- Use `calendar_service.get_economic_events(...)` (async) and `EconomicEvent` attributes (`importance`, `scheduled_at`, `title`). Refactor the admission check to be awaitable and call it before commit. Define the window as `abs(event_time - now) <= configured blackout minutes`, including events both before and after the scheduled time; normalize to UTC and handle naive provider times consistently at the adapter boundary.
- A configured positive blackout requires a trustworthy persisted/fetched calendar result. Unconfigured/unavailable calendar, malformed event, or source status `unavailable` blocks admission with a `calendar_unavailable` reason. An intentionally empty result with known successful source coverage is not treated as an outage.
- Use the existing Alpaca Trading API calendar through `alpaca-py` as the verified regular-session source; it is a credentialed read-only calendar GET, requires configured API credentials, and has published market-day coverage 1970–2029. Use only the calendar endpoint, validate returned coverage/schema, and fail closed when credentials or coverage are unavailable. No new dependency, no account/order methods, and no weekday approximation.

### Valuation and position/exposure semantics

- For order admission and held-position marks, `source_time` means the provider/exchange event timestamp, not local fetch time. Require an aware/UTC-normalizable source timestamp no more than 15 seconds old and a provider explicitly marked non-delayed (`delay_seconds == 0`). Yahoo and delayed IEX data are rejected even if just fetched; no wider freshness bound is inferred from fetch time. Keep `fetched_at` for diagnostics only. If no eligible quote exists for a held position, preserve its last trusted mark/source timestamp for reporting, set valuation stale and activate an audited owner halt; never value it at zero.
- Validate order price fields by type: LIMIT requires `limit_price`; STOP requires `stop_price`; irrelevant limit/stop fields are rejected. MARKET has no client execution price and must use a fresh conservative quote bound; STOP valuation uses its trigger and conservative slippage policy. If safe price cannot be bounded, reject before acceptance.
- A single order valuation object feeds cash/buying power, concentration, gross/net exposure and reservation calculations; each reported decision includes policy version and valuation basis.
- Compute signed projected instrument quantity (`current_qty +/- remaining_qty`), value it using a consistent current valuation, and compare absolute post-order concentration. For gross/net exposure apply position-crossing semantics, not “all sells add short” regardless of existing holdings.
- Simulated shorts are allowed only when the instrument is on an operator-managed `SHORTABLE_SYMBOLS` allowlist and borrow eligibility is explicitly configured true; unknown/missing eligibility denies. This is a simulation policy, not proof of broker borrow availability, and does not enable broker/live shorting.
- Require explicit collateral policy: no borrowed buying power; reserve additional settled owner cash equal to 100% of short notional, while segregating short-sale proceeds so neither proceeds nor collateral can fund buys/withdrawals. Enforce 10% max per-position/short notional, 200% gross exposure as an upper ceiling only (not buying power or permission to borrow), and 100% net exposure. Available buy capacity is settled free cash after reservations and separate short collateral. Compute short exposure from signed post-order positions; closing/reducing positions must be recognized as risk-reducing. Per-position session loss cap is 2% of session-opening equity, tighten-only; session total loss and peak-to-trough drawdown halt at 5% of session-opening equity.
- Apply API and provider rate limits as defense-in-depth only; frequency limits do not substitute for portfolio risk controls. Short exposure fails closed when any risk input/config is absent or unreadable.

### Reservations and actual simulated fills

- In one DB transaction, lock/serialize portfolio admission (SQLite `BEGIN IMMEDIATE` or the existing transaction discipline), reload positions and pending accepted/partially filled orders, compute risk including all remaining commitments, and persist the order plus a reservation record. Insufficient capacity rejects with no order, acknowledgment, or reservation.
- Closed-market market orders use a 2% adverse collar at the latest eligible close and expire at the next verified Alpaca regular-session close, including early closes. If required credentials, dates, schema or coverage are unavailable, deny closed-market orders rather than approximate sessions.
- Fills, partial fills, cancellations and expirations update reservation quantity/amount atomically. Pending sell reservations include available position quantity; two sells that each fit alone but together exceed the position must not both be admitted. Before applying each simulated fill, recompute actual notional/cash/exposure with fill price/quantity/commission and reject/hold the fill if the invariant would be violated. Keep event/ledger transaction consistent; no fill event may claim success without position, cash, ledger and reservation updates committing together.
- Automatic halt evaluation snapshots session-opening equity and per-position unrealized-PnL baselines at regular-session open. Apply session realized+unrealized loss, per-position session loss, and peak-to-trough drawdown against those baselines. Persist last trusted eligible mark price and source timestamp; if any held symbol lacks a current eligible non-delayed source-time mark, retain the last trusted mark for reporting, mark valuation stale, durably halt that owner, and block new exposure—never substitute zero or fetch time. Cancels remain allowed under every halt and release reservations. Strictly risk-reducing closes may bypass owner-only (not global) halt, require a fresh eligible execution bound, and may not cross zero.
- Risk review includes the existing process-local simulator and persistence semantics; if the current event-sourcing callbacks prevent atomicity, first implement transaction-safe fill application without moving broker fills into this ledger.

### Bounded fill processing

- Add a simulator entrypoint that accepts an already-loaded `order_data` object/validated `Order` so a stream does not issue a full portfolio read for each open order. Keep an ID lookup version for direct API use.
- Bound maximum pending orders at admission and set a finite per-stream batch (e.g. a small fixed page) plus pacing; no unbounded synchronous loop on the async API event loop. Use `asyncio.to_thread` or async DB only where needed and test event-loop responsiveness; do not introduce a task/queue service for this scoped fix.

## Failure behavior

Kill switch active, config missing/unreadable, blackout data unavailable/malformed, unknown valuation, pending-capacity overflow, transaction conflict, or fill invariant violation blocks the affected action. Never swallow an exception and continue. Public failures do not expose SQL/provider secrets. A paper order only becomes accepted after transaction commit.

## Regression tests

- Both manual and AI callers reject before persistence on each risk/kill-switch/blackout failure; verify no accepted order/fill.
- Correct async calendar invocation with model-object events; event inside before/after time range blocks; event outside passes; unavailable/malformed calendar fails closed; known successful empty calendar follows declared policy.
- Dashboard kill activation survives engine re-instantiation and blocks both call paths; database failure does not report successful activation/admission.
- MARKET/STOP supplied irrelevant prices rejected; LIMIT requires limit; valuation tracks proper field; conservative unknown quote failure.
- Projected long, partial close, cross-through-zero short, allowlisted vs non-allowlisted symbol, missing borrow eligibility, collateral shortage, 10% max single-position/short notional, 200% gross ceiling, 100% net cap, 2% per-position loss, and 5% daily/drawdown thresholds; verify API/provider throttles are additional rather than the sole risk gate.
- Automatic mark tests cover source-time/non-delayed freshness, open-session baseline reset, retained last trusted quote, absent/stale/delayed quote owner halt, and no zero substitution. Halt exit tests prove cancel always works and risk-reducing close works only under owner halt with fresh quote/no cross-zero.
- Two pending sells that individually fit but jointly oversell are rejected; frontend order ticket retries reuse one idempotency key and a changed order intent rotates it.
- Two accepted orders whose combined reservations exceed capacity; concurrent submissions; partial fill/cancel/expire release/consume reservations; actual fill price/commission crossing limits is not applied.
- Portfolio stream with N orders performs bounded portfolio reads (constant/bounded, not N full reloads), processes only finite batches, and remains responsive.
- Kill switch shared boundary covers every paper submission path; no live/broker order API called.

## Non-goals

- This design does not provide auth/portfolio ownership (see ownership design), broker placement, broker-origin fill ingestion, live account limits, or Phase 4 reconciliation evidence.
