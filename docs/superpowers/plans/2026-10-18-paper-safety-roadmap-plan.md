# Paper Safety and Roadmap Reconciliation Implementation Plan

> **For agentic workers:** Execute this plan inline task-by-task in the current workspace. Steps use checkbox (`- [ ]`) syntax for tracking. The user approved inline execution, no worktree, and no commits/pushes; a task checkpoint is green named tests plus a ledger entry.

**Goal:** Fail closed to paper-only behavior, make broker order attempts recoverable and truthful, add a fixture-testable but explicitly non-independent fill comparator, stabilize Strategy Studio content hashes, and reconcile project status documents.

**Architecture:** First disable unsafe broker/account access and label the UI's existing simulator honestly. A broker-paper order-intent store is separate from both the simulated ledger and the future broker-origin fill-ingestion ledger. The comparator can be implemented with synthetic fixtures now, but a real comparison gate requires separate future ingestion (3a) and opt-in soak (3c) slices. Strategy hash/version work is independent; roadmap edits come last.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, SQLite, aiohttp, pytest, React/TypeScript/Vite, Alpaca Trading API v2.

**Spec:** [Paper Safety and Roadmap Reconciliation Design](docs/superpowers/specs/2026-10-18-paper-safety-and-roadmap-design.md)

**Execution approval:** User approved this revised plan and directed that the second direct broker execution path (`broker_service.py`) be closed first. Execute inline in the current workspace; do not create a worktree or use implementation subagents. No commits/pushes.

## Global Constraints

- `GATEWAY_EXECUTION_MODE` stays `paper`; this plan never authorizes submitting/canceling any order.
- Execution requests require HTTPS host exactly `paper-api.alpaca.markets`; market-data hosts remain independent.
- Simulated, broker-order-intent, and broker-origin-fill records are separate facts; never merge or cross-label them.
- Broker order POSTs are never retried automatically after ambiguous outcomes; use exact client-order-ID lookup and retain `UNKNOWN` if resolution is inconclusive.
- Comparator can only emit real `PASS` with settled, structurally valid `evidence_kind=real` union count `n >= 1000` and `mismatches * 1000 < n`; do not run real gate in this plan.
- Preserve current market-data providers and unrelated pre-existing changes, especially `quant-app-v1/backend/.DS_Store`.
- No secrets are read/printed; no broker requests with credentials, deploys, commits, pushes, or external service provisioning. Do not commit; the user's explicit no-commit preference is met with a task checkpoint of all named tests green plus a corresponding entry in the plan ledger. Pushes remain unauthorized.
- Slice 3a and Slice 3c each require their own reviewed design and explicit future authorization before implementation/action.

## Execution order

**Security remediation dependency update:** First ship the hardening exposure stopgap and independent Auth0, AllTick, installer-disable, and current-store endpoint protections; these precede shared Foundations Task 0 and identity migration. Foundations Task 0 is explicitly owned by the ownership plan and requires real-connection concurrency/atomicity tests. Ownership Task 4 and paper-risk Tasks 1–7 are one coordinated Trade release; keep order UI and backend submission explicitly unavailable until both ship. BYOK remains blocked on deployed RPC inspection, separate migration approval, application, contract tests, and matching backend deploy; until then LLM chat is unavailable to all users, the shared operator key remains quarantined, and UI shows “Add your key” plus migration/service-unavailable state. No broker-fill reconciliation scope changes.

- Tasks 1 and 2 are the first delivery gate and must ship before later evidence-gate or documentation work.
- Task 4 is independent of Tasks 1–3 and may proceed alongside Tasks 1/2; for this native, single-implementer execution, complete it after Tasks 1/2 without blocking their safety delivery.
- Task 3 implements only fixture-backed comparator/CLI behavior, after Tasks 1/2; it can be done before or after Task 4. Task 5 is always last.
- Future Slice 3a (broker-origin fill ingestion) and Slice 3c (opt-in paper soak) are not implementation tasks in this plan. They need separate reviewed designs/plans and explicit authorization. No orders are sent here.

## Review Focus

- A crafted URL reaches a non-paper execution host through either constructor or HTTP request code: reject before network I/O; a static test forbids the live host literal in broker execution modules.
- `client_order_id` lookup returns no order during broker propagation or the process dies before/after POST: startup recovery and bounded re-lookup, never create a second POST.
- Inputs contain repeated or malformed activity IDs: exact duplicates deduplicate; conflicting/recoverable malformed rows count as mismatches; unrecoverable IDs abort with exit 2.
- `n=0` or small sample with a high mismatch rate: empty is insufficient; non-empty rate at/above threshold fails even under 1,000.
- Strategy data contains NFC-colliding keys, NaN/Inf, numeric/string lookalikes, or unordered rule lists: reject ambiguous inputs and preserve the specified semantics.
- Old strategy rows lack hashes and concurrent version creation races: leave legacy hash null until a versioned transactional backfill; allocate under `BEGIN IMMEDIATE` and retain the unique constraint.

---

## File Structure

- Modify both direct execution paths: `quant-app-v1/backend/app/services/alpaca_live.py` (later neutral rename only after its own green checkpoint) and `quant-app-v1/backend/app/services/broker_service.py` (`_AlpacaProvider`). Keep market-data `app/providers/alpaca_provider.py` outside execution-host checks. `BrokerService` is also imported by `ai_trading.py`; Task 1 must disable its live route immediately, then Task 2 may enable it only through the durable broker-order lifecycle.
- Modify/create broker order lifecycle service and SQLite tables in `quant-app-v1/backend/app/services/`: durable broker-only intent and recovery; cover every direct order submission path, including `_AlpacaProvider` in `broker_service.py`; never reuse `paper_orders`/`fills` rows for broker-order state.
- Add `quant-app-v1/backend/app/scripts/inspect_broker_order_intents.py` for read-only listing and audited local-only operator resolution of stuck `UNKNOWN` intents; it must never submit/cancel orders or contact the broker.
- Modify `quant-app-v1/backend/app/api/v1/live.py`, then move/rename route module if compatibility permits; fail-closed auth and broker route behavior.
- Modify `quant-app-v1/backend/app/services/ai_trading.py` only to block indirect broker order paths; broker execution modules must contain no live trading hostname literal (enforced by a static test).
- Add focused backend tests under `quant-app-v1/backend/tests/` for both broker execution paths, route gating, lifecycle recovery/operator resolution, and reconciliation CLI. Confirm pytest collects tests in both `backend/tests/` and `backend/app/tests/`. Fix the existing StrategySpec regression collection test without weakening its assertion; run both explicit paths and `pytest --collect-only` as evidence.
- Add comparator/CLI modules under `quant-app-v1/backend/app/services/` and `app/scripts/`; only fixture inputs in this plan.
- Modify `quant-app-v1/backend/app/models/__init__.py`, `app/api/v1/strategies.py`, and strategy tests for canonical hash and SQLite version allocation.
- Modify frontend status/order surface components located by consumers of `Live`, `Closed`, and `PAPER` badges; add focused UI tests. No broker-paper selector is added.
- Update `ROADMAP.md`, `docs/phase-2-plan.md`–`docs/phase-9-plan.md`, `docs/phase-5-prerequisites.md`, and `docs/status.md` last, with evidence-qualified status.
- Create a private plan ledger at `.superpowers/sdd/2026-10-18-paper-safety-roadmap/progress.md` during implementation; do not touch another plan's ledger.

### Task 1: Fail-closed broker routes, provider naming, and UI disclosure

Execute in three independently green-checked slices: backend guards and route gating first, then frontend disclosure, then neutral renames last (renames may be omitted only if a code/import analysis shows compatibility risk; record the ruling). Do not combine these slices before their focused tests pass.

**Files:**
- First guard `quant-app-v1/backend/app/services/broker_service.py` (`_AlpacaProvider`) as the user-prioritized gap, then guard `quant-app-v1/backend/app/services/alpaca_live.py`; do not rename before guards/routes and tests are green. If renamed later, compatibility imports must not bypass validation.
- Modify `quant-app-v1/backend/app/api/v1/live.py`; optionally rename to `paper_execution.py` only as the final 1c slice after route tests pass.
- Modify `quant-app-v1/backend/app/api/main.py`, `quant-app-v1/backend/app/services/ai_trading.py`, frontend components containing left-rail `Live`/`Closed`/`PAPER` badges and paper-order actions.
- Tests: `quant-app-v1/backend/tests/test_broker_paper_safety.py`, `test_broker_service_safety.py`, existing route/AI tests, and relevant frontend tests.

**Interfaces:**
- Provider constructor and every broker HTTP request enforce HTTPS with exact host `paper-api.alpaca.markets`, default TLS port, no userinfo, and no redirects; market-data hosts are not subject to this execution allowlist.
- The app does not mount broker mutation/account routes while optional auth and `default_user` remain; retained legacy routes, if any, are explicitly flag-off and return a stable unavailable response. Indirect AI order paths are blocked.
- UI status labels distinguish `Simulated paper`, `Live execution unavailable`, and market `Closed`.

- [x] **1a — backend first:** Added failing tests for `broker_service.py` default/non-paper config, crafted scheme/host/port/userinfo, every-request host allowlist, redirect refusal, and no broker submission while durable lifecycle is absent. `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_broker_service_safety.py` failed 10 tests before implementation (all targeted defects observed). Route/UI and `alpaca_live.py` coverage remains for the next 1a slices.
- [x] Implemented first execution path: exact HTTPS `paper-api.alpaca.markets` authority validation at `_AlpacaProvider` construction and every request, default port only, no userinfo/path/query/fragment, no redirects, explicit order-state mapping, and fail-closed `place_order` until durable intent/recovery is integrated. No market-data provider hosts changed.
- [x] Verify first execution-path checkpoint: `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_broker_service_safety.py tests/test_phase0_safety.py tests/test_phase4_paper_portfolio.py` → 31 passed; `py_compile app/services/broker_service.py tests/test_broker_service_safety.py` and targeted `git diff --check` passed. Existing portfolio deprecation warnings remain.
- [x] **1a remainder — backend fail-closed:** Also guarded `AlpacaLiveProvider` with the shared exact paper-origin validator, revalidated request URLs, refused redirects, made placement fail closed, and mapped broker statuses explicitly. Unmounted the entire `/live` router (private reads, mutations, and account-control routes) from the app; `get_provider()` returns stable 503 if called internally. Blocked indirect AI live order submission and forced saved/API AI route configuration to paper. Tests prove route absence, no AI submit, no live host literal in execution modules, and paper-only defaults.
- [x] **1b — frontend second:** UI labels identify `Simulated paper`, explicit market status `Open/Closed/Unknown`, and `Live execution unavailable`; old live view renders an unavailable page, and simulator order helpers no longer expose broker calls. Focused Playwright `paper-safety.spec.ts` (2 tests) and `npm run build` passed. The test verifies an order request goes only to `/portfolio/orders`, with no `/live` request.
- [x] **1c — names ruling:** Kept legacy module/class names for compatibility; route unmount and provider fail-closed guards are explicit. Renaming is not necessary to enforce safety and could break internal imports; static host-literal regression covers both execution modules.
- [x] Task 1 checkpoint: from backend, `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_broker_service_safety.py tests/test_broker_paper_safety.py tests/test_phase0_safety.py tests/test_phase4_paper_portfolio.py` → 45 passed; Python compilation passed. Frontend from `quant-app-v1/frontend`: `npm run build` passed, `npm run test:e2e -- --grep 'paper desk discloses simulator mode|live execution view'` → 2 passed. Vite produced its existing large-chunk advisory; backend emitted existing deprecation warnings.

### Task 2: Durable broker-order intent and recovery

**Files:**
- Modify/create `quant-app-v1/backend/app/services/broker_order_store.py` and supporting SQLite definitions in `app/services/database.py`.
- Modify broker-paper adapter and route module from Task 1.
- Test: `quant-app-v1/backend/tests/test_broker_order_recovery.py` plus adapter tests.

**Interfaces:**
- `persist_order_intent(order: BrokerOrderIntent) -> BrokerOrderIntent` commits an `INTENT_PERSISTED` record before any broker POST; definitive POST response becomes `SUBMITTED`, ambiguous transport outcome becomes `UNKNOWN`, and a lookup that establishes broker identity becomes `RESOLVED` with `broker_order_id` plus a separate current `broker_status`. `RESOLVED` means identity is known, not that the order is terminal.
- `list_unresolved_order_intents() -> list[BrokerOrderIntent]` returns `INTENT_PERSISTED`, `SUBMITTED`, and `UNKNOWN` records for startup recovery.
- `resolve_order_intent(client_order_id: str, lookup: Callable[..., BrokerLookupResult], *, clock: Callable[[], datetime], sleep: Callable[[float], Awaitable[None]]) -> BrokerOrderResolution` uses injected time/sleep; lookup outcomes are `FOUND`, definitive HTTP `NOT_FOUND` (404 only), or `INCONCLUSIVE` (timeout/transport error/5xx/other status). Only three definitive 404s across immediate plus two delayed checks count as not-found; inconclusive checks never increment that count. Found order sets `RESOLVED` (identity known) and stores `broker_status` separately; absent three definite 404s, retain `UNKNOWN`. Never repost.
- Startup invokes a recovery sweep over all unresolved records, looking up the exact `client_order_id` before any operator action. BrokerService's `_AlpacaProvider` must use this same intent-before-POST/recovery contract or have order submission disabled; it may not remain a parallel untracked POST path. Alpaca documents a 128-character client ID maximum, lookup by `GET /v2/orders:by_client_order_id?client_order_id=...`, and duplicate submission rejection (not replay); do not assume undocumented uniqueness duration.
- `inspect_broker_order_intents.py --list` is read-only. Its explicit `--resolve` operation writes an audit event and requires a verified `broker_order_id`, `broker_status`, and evidence reference; it changes only local resolution metadata and never contacts or mutates Alpaca.
- `place_order` sends `client_order_id`, order type, TIF and valid limit/stop prices, with no POST retry or redirect following.

- [x] Task 2 decision/checkpoint: do not add a durable intent store in this increment. Since account ownership is not solved and no reviewed lifecycle implementation was ready, both broker adapter `place_order` paths remain fail-closed. Evidence: focused adapter safety tests assert submission raises before network; no broker credentials or broker API requests used. Durable intent/recovery, operator resolution CLI, and their full lifecycle tests remain **not started / gated**, not delivered.

### Task 3: Comparator schema, CLI and evidence result

**Files:**
- Create `quant-app-v1/backend/app/services/paper_fill_reconciliation.py`.
- Create `quant-app-v1/backend/app/scripts/compare_paper_fill_exports.py`.
- Test: `quant-app-v1/backend/tests/test_paper_fill_reconciliation.py` and CLI invocation tests.

**Interfaces:**
- `compare_exports(local: ExportDocument, broker: ExportDocument, *, now: datetime) -> ReconciliationReport`.
- `ReconciliationReport` contains `result` (`PASS|FAIL|INSUFFICIENT_EVIDENCE`), `evidence_kind`, `n`, `mismatch_count`, classified IDs, diagnostics, windows, settle state, and sources.
- The export schema and all field names are **provisional** until the separate 3a design validates them against a real Alpaca activity sample; do not treat `gateway-paper-fill-export/v1` as a settled ingestion contract. `source_origin` is Alpaca for both exports, while `source_retrieval` distinguishes `gateway_broker_fill_ledger` from `alpaca_account_activities`; reject same retrieval IDs/artifacts and never accept simulator ledger data as local evidence.
- Provisional manifest requires `retrieval_complete`, pagination metadata (`page_count`, stable page ordering, hashed page-token identifiers), and for Alpaca-side export request metadata (endpoint, sanitized params, retrieval start/end) plus SHA-256 for each raw response page. 3a design may change this before schema freeze.
- Provisional `settle_margin` defaults to 5 minutes (`DEFAULT_SETTLE_MARGIN = timedelta(minutes=5)`), is recorded in each manifest, and remains subject to 3a sample validation; `settled_through >= window_end + settle_margin`.
- Compare quantity/price as exact `Decimal`, never binary floats. Provisional default tolerances are quantity `0`, price `0` (exact equality after Decimal parsing), and equivalent timestamp instants `0 seconds`; if the 3a sample establishes source-format quantization differences, only an explicitly recorded reviewed tolerance may relax them.
- CLI: `python -m app.scripts.compare_paper_fill_exports --local FILE --broker FILE --report FILE`; exits 0 PASS, 1 FAIL, 3 INSUFFICIENT_EVIDENCE, 2 malformed/I/O/tool error.

- [x] Task 3 checkpoint decision: comparator/CLI deferred rather than shipping an unvalidated schema without the full test/fixture contract. `app/services/reconciliation.py` remains a stub and the existing `verify_paper_trade_reconciliation.py` is not treated as a broker-fill comparator. No real or synthetic comparator PASS is claimed. The real evidence gate remains insufficient pending separate 3a ingestion design and 3c user-opt-in soak authorization.

### Future gated slices (not executed by this plan)

- **Slice 3a — broker-origin fill ingestion:** after a separate design/review/plan approval, build the append-only local ledger for Alpaca-origin fills only. Keep it separate from simulator fills and broker-order intent/state; real comparison evidence is impossible before 3a is accepted.
- **Slice 3c — opt-in paper soak:** after 3a and the required auth, ownership, risk limits, kill/stop controls, and paper-host verification exist, design an explicitly user-opted, rate-limited market-hours harness with tiny quantity/notional caps, a strict order/fill count limit, immediate user stop, and durable audit. This is the planned source for up to 1,000 settled real paper fills; it is not authorized or implemented here. The comparator remains `INSUFFICIENT_EVIDENCE` until those fills exist and meet the settled-window rules.

### Task 4: StrategySpec canonical content hash and atomic version allocation

**Files:**
- Modify `quant-app-v1/backend/app/models/__init__.py`.
- Modify `quant-app-v1/backend/app/api/v1/strategies.py`.
- Modify `quant-app-v1/backend/app/tests/test_strategy_spec_regression.py` and add `quant-app-v1/backend/tests/test_strategy_content_hash.py`.
- If strategy_versions DB migration is needed, modify existing strategy DB init in `strategies.py` and test old DB compatibility.

**Interfaces:**
- `canonical_strategy_payload(spec: StrategySpec) -> bytes` implements the exact tagged JSON tree and list semantics in the spec.
- `compute_strategy_content_hash(spec: StrategySpec) -> str` hashes `b"gateway-strategy-spec:v1:" + canonical_strategy_payload(spec)`.
- `StrategySpec.content_hash: str | None` is an input assertion; computed digest is persisted separately in nullable `strategy_versions.content_hash`.

- [x] Fixed the dynamic-test Pydantic import by registering its module before execution and exposing `Any`; kept and passed the deterministic ID assertion by explicitly sharing the same timestamp and ID inputs. `PYTHONPATH=. ./.venv/bin/pytest -q app/tests/test_strategy_spec_regression.py` passed.
- [x] Added canonical tagged-tree hashing, normalized Decimal/NFC handling, collision/nonfinite rejection, semantic/list rules, content-hash assertion validation, rule free-text fail-closed validation, nullable `strategy_versions.content_hash` migration, hash exclusion from stored specs, and `BEGIN IMMEDIATE` version allocation. Legacy rows remain nullable (no backfill is attempted until they can be safely parsed under this contract).
- [x] Added tests for key ordering, decimal equivalence, NFC collision, set-vs-sequence semantics, excluded metadata, text-only rule rejection, supplied hash, nonfinite values, primitive type distinctions, stored hash separation, legacy null, and concurrent version creation.
- [x] Task 4 focused checks: `PYTHONPATH=. ./.venv/bin/pytest -q tests/test_strategy_content_hash.py app/tests/test_strategy_spec_regression.py` → 13 passed; changed modules `py_compile` passed. Broader adjacent selection hit one unrelated existing fixture error: `test_phase0_catalogue.py::test_stocks_metadata_includes_catalogue_fields` mocks `fetch_ohlcv` without new `as_of` kwarg; full failure was observed and not modified here.

### Task 5: Reconcile product roadmap and status evidence

**Files:**
- Modify `ROADMAP.md`, `docs/phase-2-plan.md` through `docs/phase-9-plan.md`, `docs/phase-5-prerequisites.md`, `docs/status.md`.

**Interfaces:**
- Status uses exactly `implemented`, `verified`, `partially verified`, `blocked`, `not started` labels where applicable.
- Every verification claim names a command and evidence path; synthetic comparator checks are not real evidence.

- [x] Re-read targeted phase/status docs and compare completion claims with current source and test output; stale adapter and execution-path inventories corrected in `docs/phase-5-prerequisites.md`.
- [x] Update phase dependency gates, distinguish simulated ledger, broker-order intent, and broker-origin fill ingestion, and reserve future 3a/3c for separate reviewed design/authorization.
- [x] State the ≥1,000 settled real-fill / <0.1% evidence gate is insufficient and live readiness is not established in `ROADMAP.md` (ignored local file), `docs/status.md`, and Phase 4–9 docs.
- [x] Read-only secret-pattern scan over changed docs/source returned 0 matching files; scan used a local Python regex because `rg` is unavailable in this environment, matching values were not printed.
- [x] Focused backend tests: 58 passed in the combined adjacent selection; changed-module `py_compile` passed. Frontend `npm run build` and two focused Playwright tests passed. Full `pytest -q` is blocked during collection (64 errors), primarily vendored optional dependencies/yfinance API mismatch plus SciPy binary loader; see `docs/status.md` and the ledger.
- [x] Review final changed files and `git diff --check`; whitespace check passed. Preserved the pre-existing `.DS_Store` modification and restored generated `frontend/dist/index.html` to baseline. `ROADMAP.md` is ignored and absent from HEAD, so its workspace update is not part of the normal Git diff. Claims match recorded evidence and blockers.

## Self-review / coverage

- Execution boundary, route auth, status UI, redirect protection, broker order recovery, and fail-closed persistence are Tasks 1–2.
- Fill ledger separation, comparator rules, exact rate math, malformed data, windows, evidence kind, and exit codes are Task 3; actual broker ingestion is explicitly a separately designed future 3a; soak is future 3c.
- Strategy canonicalization, exact semantic/list rules, legacy null/backfill, hash validation, free-text-only collision policy, stored-spec hash exclusion, and SQLite concurrency are Task 4.
- Task 3's manifest remains provisional until 3a's sample-based schema review; exact Decimal comparison and zero default tolerance are the current safe provisional behavior. Closed-window and settle-edge fixtures plus the `n=999,m=0` case are required.
- `RESOLVED` means known broker order identity only; broker lifecycle status is a separate nonterminal-capable field. Only definitive 404 contributes to not-found count; retries use injected clock/sleep. Stuck intents have a tested local operator inspect/resolve procedure.
- Task 1 is staged backend boundary/routes -> frontend labels -> optional module renames with green checks at each stage; `broker_service.py` is explicitly a second direct execution path and the live-host scan covers both execution modules.
- No commits are made; each task checkpoint is green named tests plus a ledger entry, honoring the user's explicit no-commit instruction without claiming delivery before evidence.
- Roadmap/status updates and secret scan are Task 5.
- Dependency order is explicit: Tasks 1/2 are the first delivery gate; Task 4 is independent and may run alongside them; Task 3 is fixture-only; Task 5 is last. No task enables live execution, submits/cancels an order, or makes a broker request. UI work is included because broker routes are unmounted/disabled.
- Defense in depth covers exact host checks at construction and every request plus a static live-host exclusion regression; crash recovery covers process death on both sides of POST; activity filters use UTC-normalized typed params; verification includes a read-only secret-pattern scan with matching lines suppressed.
- Review focus cases are assigned to Tasks 1–4. The existing full-suite collection failures remain reported, not suppressed.
