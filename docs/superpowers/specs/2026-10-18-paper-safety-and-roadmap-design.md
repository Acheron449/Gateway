# Paper Safety and Roadmap Reconciliation Design

**Date:** 2026-10-18
**Status:** Draft for user review; no implementation authorized by this document alone.

## Goal

Make Gateway's existing US-equities research and simulated paper-trading system truthful, reproducible, and fail-closed before considering any broker-paper or live-execution capability; then reconcile its roadmap and status documents with actual code and verification evidence.

## User intent and success criteria

The user asked for the revised roadmap to be worked through autonomously in an optimal sequence and revised on completion, natively without subagents. This is a safety-first software improvement request, not authorization to submit paper or live orders. Success means:

1. Broker-facing code fails closed to the exact Alpaca paper host, and broker order/account routes remain unavailable until authenticated identity and account ownership are enforced.
2. Paper order attempts have durable intent/recovery semantics, preserve order parameters, map broker states, and distinguish validation, rejection, and uncertain outcomes without blind POST retries.
3. The current simulator ledger stays distinct from any future broker-origin intent/order-state or fill-ingestion ledger; no order/fill is merged, substituted, or cross-labeled.
4. A fixture-testable comparator has a three-valued result and exact denominator/threshold rules, while explicitly remaining unable to produce real `PASS` until broker-fill ingestion (3a) and a separately authorized soak harness (3c) exist.
5. Strategy reproducibility has an exact, versioned canonicalization contract, preserves current `strategy_id` and immutable version semantics, and handles legacy rows safely.
6. Frontend status is truthful about `Simulated paper`, market-closed state, and `Live execution unavailable`; disabled routes do not fail as generic network errors.
7. Roadmap/status documents reflect source and verification evidence. Focused and broad checks are reported with actual outcomes and existing blockers.

## Existing context verified

- The active backend is FastAPI under `quant-app-v1/backend/app`; existing market-data providers include Yahoo Finance, Alpaca, Finnhub, TradingView, AllTick, CCXT, and London Strategic Edge. OpenBB is not a historical-data provider. No replacement data vendor is required.
- `app/config.py` enforces `GATEWAY_EXECUTION_MODE=paper`, but `app/api/v1/live.py:get_provider()` defaults to Alpaca's live URL and `paper=false`; it constructs `AlpacaLiveProvider` directly.
- `AlpacaLiveProvider` has live defaults and accepts caller endpoints; its in-memory idempotency expiry is broken, it uses a non-Alpaca `Idempotency-Key` header, retries POST after network failures, hand-builds query strings, and does not preserve all broker states. Redirects need an explicit no-follow policy.
- `services/broker_service.py:_AlpacaProvider` is a second direct execution path used by `BrokerService`; it has a substring paper-host check that accepts crafted authorities, follows redirects by default, maps many broker states to `PENDING_NEW`, and submits without `client_order_id` or durable intent. It must receive the same execution-host checks and durable-lifecycle integration as `AlpacaLiveProvider`, or remain fail-closed from order submission until integrated. Static live-host regression covers both execution modules; market-data `providers/alpaca_provider.py` is excluded.
- Current official Alpaca Trading API docs say Trading API v2 `client_order_id` may be up to 128 characters, document lookup by `GET /v2/orders:by_client_order_id?client_order_id=...`, and document duplicate submissions as rejected—not replayed as the original order. Uniqueness duration remains unclear. Account activities paginate with `page_size` and `page_token`; `after`/`until` filter on activity `created_at`, not a documented execution timestamp. Sources: [Create an Order](https://docs.alpaca.markets/us/reference/postorder), [Get Order by Client Order ID](https://docs.alpaca.markets/us/reference/getorderbyclientorderid), [Working with /orders](https://docs.alpaca.markets/us/docs/working-with-orders), [Account Activities](https://docs.alpaca.markets/us/reference/getaccountactivities-2), [Paper Trading](https://docs.alpaca.markets/us/docs/paper-trading). Treat anything not documented there as unresolved.
- `paper_portfolio.py` and `database.py` implement a `FillSimulator`-backed **simulated** paper ledger, not Alpaca fill ingestion. `services/reconciliation.py` is a stub. Simulated-paper facts and broker-origin intent/order-state/fill facts are distinct data classes and stores. Never merge, relabel, or substitute them. API/UI must label execution mode `simulated_paper` or `broker_paper` precisely.
- `live.py` is mounted with `get_current_user_optional`; user-specific live gates, agreements, limits, and kill-switch state use hard-coded `default_user`. Optional auth is not a production account boundary.
- Strategy Studio consumes `app/models/__init__.py:StrategySpec` (`strategy_id`, `version`). A separate draft exists at `app/models/strategy.py`; its regression test currently fails collection because dynamic loading hides `Any` from Pydantic.
- `quant-app-v1/backend/.DS_Store` is already user-modified and unrelated; leave it untouched. Full pytest collection has known environment/collection blockers documented in `docs/status.md`.

## Architecture and approach

Use existing components and providers, with narrow changes. First close unsafe execution configuration, disable broker/account-specific route access until real ownership checks exist, and make any broker order lifecycle durable and non-retrying. Keep three separate concepts explicit: (1) the existing simulated-paper ledger; (2) a broker-paper order intent/state store required for durable submission recovery; and (3) the future append-only broker-fill ingestion ledger required for reconciliation. These stores represent different facts and must never be merged or cross-labeled.

The future reconciliation compares Gateway's persisted copy of broker-origin Alpaca paper fills against a separately retrieved copy of Alpaca paper activities. Both share Alpaca as source origin. This measures Gateway ingestion/persistence completeness, not independent execution quality. Do not compare simulator-generated fills to broker fills.

Strategy reproducibility applies to the model used by Strategy Studio. Add a versioned canonical hash without repurposing `strategy_id`, keep immutable `strategy_versions.spec`, and store hash metadata separately. Keep the unrelated draft schema out of production until consumer analysis resolves its status.

## Work sequence

### Workstream 1 — Fail-closed execution boundary and truthful frontend status

- Preserve `GATEWAY_EXECUTION_MODE=paper`.
- Rename `AlpacaLiveProvider` to a neutral broker-paper adapter and `live.py` to a paper-execution route module where compatibility permits. Otherwise retain compatibility aliases that warn and reject live mode. Update imports and callers together so no legacy alias bypasses safety.
- At both adapter construction and HTTP/API configuration boundaries, require HTTPS host exactly `paper-api.alpaca.markets`, default TLS port, no userinfo, and no alternate host. Do not accept an arbitrary execution `ALPACA_BASE_URL`. Keep market-data provider hosts independent from execution-host checks.
- Disable order-changing endpoints (`POST /live/orders`, `DELETE /live/orders`, `DELETE /live/orders/{order_id}`) until authentication and account ownership are enforced. Also disable or authorize broker-private reads (`/live/account`, positions, orders, activities, idempotency, reconciliation) and account-specific agreements, limits, activation gates, and kill-switch controls. `get_current_user_optional` and `default_user` are insufficient. Ensure indirect entry, including AI trading, cannot reach broker submission. Public health must not expose account identifiers or provider errors.
- Configure the trading HTTP client not to follow redirects; reject 3xx responses without forwarding auth headers.
- Add runtime host/flag tests and a static regression test preventing the live trading hostname from appearing in broker execution modules; allow references in tests/docs. Exclude market-data adapter hosts from that scan.
- Frontend: replace misleading `Live` status with `Live execution unavailable`; label the simulator order path `Simulated paper`; make `Closed` explicitly a market state, not execution state; make any `PAPER` badge distinguish simulated vs broker-backed. Disabled routes should show unavailable state and disable submit/cancel controls, not surface generic network errors. Do not show a broker-paper selector before Slice 3a is accepted.
- Test unsafe config/default resolution, exact allowlist including URL userinfo/port/scheme/host attacks, no broker network call, auth-disabled route responses, no indirect submission, public health redaction, and UI labels/disabled controls.

### Workstream 2 — Durable broker-order intent and correct broker lifecycle

- Use Alpaca Trading API v2 `client_order_id` (max 128 chars per current docs) as the stable lookup key; remove the custom `Idempotency-Key` header. Duplicate POST is documented as rejection, not response replay. Use documented lookup to resolve; do not assume ID uniqueness lifetime beyond documentation.
- Persist broker-order intent/client ID before POST in a broker-only order lifecycle store, separate from both the simulated ledger and the future fill-ingestion ledger. Lifecycle states are `INTENT_PERSISTED → SUBMITTED | UNKNOWN → RESOLVED`, with broker order ID and attempt/error metadata. Intent/order-state is not a fill; do not synthesize or promote fills without broker evidence.
- Lifecycle states are `INTENT_PERSISTED → SUBMITTED | UNKNOWN → RESOLVED`. `RESOLVED` means broker order identity is known, not that the order is terminal; persist `broker_order_id` and current `broker_status` separately (which may be accepted/open). On startup, look up stuck intents by exact client ID. Only definitive HTTP 404 counts as not found; timeout, transport failure, 5xx, and other unexpected statuses are inconclusive and do not increment the not-found count. Use an injectable clock/sleep, immediate lookup, bounded in-flight grace, and two delayed lookups; three definitive 404s leave the record `UNKNOWN`; never infer absence from one lookup and never silently POST again. Inconclusive orders require controlled operator resolution through a read-only/local-audit operator tool or runbook.
- Never automatically retry order-creation POST after transport failure. Bounded read-only GET retries are acceptable. Disable redirects.
- Map `new`, `accepted`, `partially_filled`, `filled`, `canceled`, `expired`, `rejected`, `pending_cancel`, `pending_replace`, and terminal states explicitly. Preserve client ID, type, time-in-force, limit and stop prices. Reject missing required prices for limit/stop orders.
- Accept valid US-equity dotted/hyphenated symbols but reject placeholders/malformed values. Use Decimal-safe money parsing/rounding where broker/API contract permits; do not gratuitously change quantity semantics.
- Normalize `after`/`until` to UTC and pass query values as typed `params`, never hand-concatenated strings (avoid `+00:00` decoding as a space). For activities use documented `FILL` endpoint and page-token pagination. Keep `activity_created_at` distinct from execution/fill timestamps; do not assert equivalence without evidence.
- Separate validation errors, broker rejections, and uncertain network outcomes. Fail closed if DB initialization or local intent persistence fails.
- Keep simulated and broker stores separate. Add tests for both broker execution paths: status mapping, payloads, duplicate IDs, persist-before-send, ambiguous failure lookup, no duplicate POST, process crash on either side of POST, recovery grace/re-lookups (clock and sleep injected), only-404 not-found counting, redirect handling, and persistence failure. Until each direct path is lifecycle-integrated, order submission through it remains disabled.

### Workstream 3 — Three separately gated broker-fill evidence slices

#### Slice 3a — Broker-origin fill-ingestion ledger (separate design/review required)

This is a substantial subsystem and requires its own written design, review, implementation plan, and acceptance gate **before** code changes. It is not the current simulator ledger and is not the broker-order intent store.

- Implement a new append-only broker-paper fill ledger for broker-origin facts only: Alpaca activity/fill ID, broker order ID, client order ID, non-secret account/environment ID, symbol, side, executed quantity, execution price, broker execution timestamp when available, activity `created_at`, source, capture time, and secret-redacted provenance.
- Simulated fills stay in the existing simulated ledger; broker-origin fills stay in the new ingestion ledger. Never merge, convert, substitute, migrate, or cross-label facts. Both API and UI identify execution mode unambiguously.
- Ingestion is read-only with respect to the broker and append-only locally. Deduplicate stable activity IDs; preserve corrections/revisions as new linked facts instead of mutating history.
- Acceptance: reviewed schema/retention, exact paper-host enforcement, idempotent pagination, duplicate/revision and redaction tests, and proof that no simulator data was copied/relabelled. The real 1,000-fill gate cannot run until 3a is complete.

#### Slice 3b — Read-only comparator and CLI (may be implemented now with fixtures)

- Comparator takes two separate UTF-8 JSON exports: local broker-origin ledger snapshot and separately retrieved Alpaca paper `FILL` activity snapshot. Both share Alpaca as `source_origin`; the retrieval paths must be distinct. The check proves Gateway ingestion completeness/consistency, not independent execution quality. Never compare simulator fills.
- Provisional manifest proposal `gateway-paper-fill-export/v1` has `source_origin`, `source_retrieval`, `evidence_kind` (`real` or `synthetic`), `environment: "paper"`, non-secret `account_id`, distinct `snapshot_id`/`retrieval_id`, `captured_at`, closed UTC `window_start`/`window_end`, `settle_margin` (provisional default 5 minutes), `settled_through`, `retrieval_complete`, pagination metadata, request metadata and raw-response SHA-256 hashes for Alpaca-side pages, and `fills`. Each fill has `activity_id`, `order_id`, `client_order_id`, `symbol`, `side`, Decimal-string `qty`/`price`, `executed_at`, and `activity_created_at`; nullable timestamps are allowed only when source semantics do not provide them. Slice 3a must validate this provisional schema against a real Alpaca activity sample before schema freeze.
- Define the gate window on Alpaca activity `created_at`, since official filters use that timestamp. Manifests declare the same closed `[window_start, window_end]`, `settled_through >= window_end + settle_margin`, and `captured_at >= settled_through`. Fetch with `after=window_start-settle_margin`, `until=window_end+settle_margin`, then select `activity_created_at` within the exact closed interval. Keep capture/query and comparison windows distinct. If either export is not settled/complete, return `INSUFFICIENT_EVIDENCE`, not an orphan mismatch.
- Match stable activity ID first; broker order/client IDs are cross-checks. Compare symbol/side exactly, quantity and price as exact `Decimal` values, and only semantically equivalent timestamp instants under explicit tolerances (provisional defaults: qty 0, price 0, timestamps 0 seconds). Any nonzero tolerance must be recorded and justified from a reviewed source sample. Denominator `n` is the **union of unique local and broker activity IDs**, each counted once, not matched rows. Affected ID counts once as a mismatch for orphan, conflicting duplicate facts, malformed recoverable row, or any field mismatch; emit every field diagnostic. Exact repeated rows with identical facts are deduplicated and reported without extra denominator/mismatch.
- Malformed row with recoverable ID counts as mismatch. Unrecoverable identity or structurally invalid export is a tool/data error (exit 2); malformed data must never disappear into insufficient evidence and hide a failure.
- Result is `PASS`, `FAIL`, or `INSUFFICIENT_EVIDENCE`; always include `evidence_kind`. Synthetic fixtures can never return PASS. Decision precedence for structurally valid, settled evidence: `n > 0` and `mismatches * 1000 >= n` means FAIL even if `n < 1000`; `n == 0` means INSUFFICIENT_EVIDENCE; below-threshold error with `n < 1000` means INSUFFICIENT_EVIDENCE; only real evidence with `n >= 1000` and `mismatches * 1000 < n` can PASS. Thus 1 mismatch in 1,000 fails exactly at 0.1%, while 1 in 1,001 is below threshold. Reused artifact/snapshot, same retrieval, missing metadata, or unsupported semantics are INSUFFICIENT_EVIDENCE.
- CLI exit codes, mutually exclusive: `0` PASS, `1` FAIL, `3` INSUFFICIENT_EVIDENCE, `2` malformed input/I/O/tool error. Report denominator, matched/local-only/broker-only IDs, malformed/duplicate counts, per-field mismatches, tolerances, window/settle data, provenance, evidence kind, sample sufficiency and result.
- Fixture tests: exact match; exact-Decimal values; field mismatch; both orphan directions; exact repeated duplicate vs conflicting duplicates; recoverable/unrecoverable malformed rows; threshold boundaries including `n=999,m=0` -> `INSUFFICIENT_EVIDENCE`; bad-rate small sample -> FAIL; under-sampling with good rate -> INSUFFICIENT_EVIDENCE; synthetic cannot PASS; reused-snapshot/retrieval rejection; incomplete pagination/raw-response hash metadata; closed-window inclusive start/end and settle-margin edge behavior. No broker requests or credentials in this increment.

#### Slice 3c — Opt-in paper soak harness (later, separately authorized)

- Real 1,000-fill evidence cannot run until both 3a and 3c exist. 3c depends on authenticated ownership, Workstream 2 durable recovery, pre-trade risk limits, kill/stop controls, and verified paper-only host enforcement.
- Requires separate design/review, explicit user opt-in, paper credentials, market-hours policy, strict rate/count limits, tiny quantity/notional caps, immediate user stop, and durable audit trail. Paper host only.
- Do not implement/run 3c or submit/cancel any order in the current increment.

### Workstream 4 — Strategy specification reproducibility

- Prove `app/models/__init__.py:StrategySpec` is the consumed Strategy Studio contract and preserve persisted/request shape unless a separate migration is approved.
- Hash exact canonical semantic content with SHA-256. Canonical typed JSON tree: scalar tags are `["null"]`, `["bool", value]`, `["string", NFC_value]`, `["decimal", normalized_decimal_string]`; arrays are `["array", [canonical_items...]]`; objects are `["object", [[NFC_key, canonical_value], ...]]` sorted lexically on NFC key. This prevents type/object collisions. Normalize strings/keys to NFC and reject collisions; parse numbers with `Decimal(str(value))`, reject NaN/Inf, normalize signed zero to `0`, represent finite Decimal values without exponent or trailing zeros. Serialize compact UTF-8 JSON without ASCII escaping; prepend `gateway-strategy-spec:v1:` before hashing.
- List semantics: `universe` is order-insensitive, uppercase, NFC-normalized, deduplicated, and sorted. `tags` are non-semantic and excluded. Nested set-like lists `allowed_sessions`, `event_importance`, `allowed_currencies`, `blocked_currencies`, and `blocked_windows` are order-insensitive, deduplicated and sorted by canonical encoding. Top-level `entry_rules`, `exit_rules`, `sizing_rules`, `invalidation_rules`, `session_rules`, and every list inside structured `condition`/`parameters` are order-sensitive. No revision-sequence field currently exists; future lists default to order-sensitive unless a schema-versioned contract says otherwise.
- Exactly non-semantic/excluded: `strategy_id`, `version`, strategy-level `name`, `description`, `tags`, `created_at`, `created_by`; each rule's `id`, `description`, `text`. All other fields, including priority/enabled/conditions/parameters, are semantic. Because excluding `text` alone would make text-only rules with different prose collide, content hashing/persistence must fail closed when an executable rule has non-empty `text` but no structured semantic condition/parameters; require structured fields rather than silently treating prose as hash-equivalent. Prove this rule with a regression test.
- Add `content_hash: str | None = None` as an API assertion field excluded from serialized `spec`; persist the computed digest in a separate nullable `strategy_versions.content_hash`, not inside immutable `spec`. Verify supplied digest and reject mismatch. Legacy rows remain null until transactionally lazy-backfilled from stored `spec`; never trust a historical caller digest.
- Keep existing `strategy_id`; `strategy_versions` already has `UNIQUE(strategy_id, version)`. Begin SQLite `BEGIN IMMEDIATE` before reading current version; allocate version and insert spec/hash in one transaction. Roll back and return a clear conflict on integrity race.
- Never `eval` free-form rule text. Typed executable grammar is separate design work. Resolve/retire the unused draft model only after import/consumer analysis.
- Tests cover object-key order, Decimal-equivalent numbers, NFC, set-like vs ordered lists, NFC key collisions, semantic changes, supplied-hash mismatch, NaN/Inf, numeric vs string values including `true` vs `1`, text-only rule rejection, `content_hash` excluded from stored `spec`, immutability, SQLite version race, null-hash lazy backfill, and no eval.

### Workstream 5 — Roadmap, status and next gates

- Reconcile `ROADMAP.md`, phase plans 2–9, `docs/phase-5-prerequisites.md`, and `docs/status.md` against source and actual checks. State simulator vs broker ledger distinction and that real reconciliation depends on 3a + 3c.
- Use one phase numbering; record US equities/paper as current scope; preserve existing providers and verified as-of filtering.
- Correct stale claims only after source confirmation; distinguish **implemented**, **verified**, **partially verified**, **blocked**, and **not started**, with evidence paths/commands.
- Do not claim 1,000 fills, legal/security approval, live authorization, external-vendor setup, or live readiness without evidence. Keep Phase 5 live, Phase 8 external services, and Phase 9 autonomous order taking gated; Phase 6 OpenBB is research/context only and remains subject to licensing review.
- Sequence: Workstreams 1/2 plus minimal frontend status; independent Workstream 4 may proceed alongside. Workstream 3b comparator/fixtures can be implemented before 3a but cannot PASS real evidence before 3a + 3c. Slice 3a requires its own design/review/plan/acceptance before implementation. Slice 3c later and user-opt-in. Documentation reconciliation last. Do not attempt all roadmap phases in one increment.

## Global safety constraints

- Simulated, broker-order-intent, and broker-origin-fill records are distinct facts/stores; never merge, relabel or substitute one for another.
- `GATEWAY_EXECUTION_MODE` stays `paper`. Do not submit/cancel any orders or invoke broker APIs with credentials. Tests use fakes/fixtures.
- No secret files/credentials are read or printed. No deployment, publishing, commit, push or external project provisioning.
- Leave pre-existing `quant-app-v1/backend/.DS_Store` untouched. Do not change market-data providers absent separately reviewed need.
- No fixture can masquerade as real gate evidence.

## Verification strategy

- TDD where practical; targeted backend tests from `quant-app-v1/backend` with project venv and `PYTHONPATH`.
- Run py_compile, focused broker/portfolio/provider/as-of/strategy checks, then broad pytest; preserve and report actual exit status and collection blockers.
- Read-only secret scan changed files; suppress matching lines and report only file names/counts/status.
- Frontend checks prove left-rail does not claim live capability, `Closed` is market state, simulator orders say `Simulated paper`, disabled broker routes show `Live execution unavailable` with submit/cancel disabled, and no broker-paper selector exists before 3a; run frontend typecheck/build.
- Comparator tests use synthetic fixtures only and validate CLI exit codes. Report real gate `INSUFFICIENT_EVIDENCE` until 3a + 3c and valid settled paper records exist; comparison proves ingestion consistency, not execution quality.
- Inspect final files and diff; run `git diff --check`; preserve unrelated worktree changes.

## Explicit non-goals

- Enable/deploy live trading, change paper-only mode, submit/cancel any order, connect to live Alpaca, or promise a live date.
- Replace providers, use OpenBB for history, build entire roadmap at once, add an LLM executor, or `eval` free-form rules. Slice 3a may add a table in existing SQLite but must never reuse simulated-ledger rows/IDs.
- Claim real 1,000 fills, mismatch <0.1%, compliance sign-off, pen test, or live readiness from tests/synthetic data. Do not implement or run the later soak harness without separate approval and explicit user opt-in.
