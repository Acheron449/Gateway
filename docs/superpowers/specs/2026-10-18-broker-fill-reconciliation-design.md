# Broker-Fill Ingestion and Reconciliation Evidence

**Date:** 2026-10-18  
**Status:** Draft for separate review; no broker access, ingestion code, credentials, or soak activity authorized by this design.

## Goal

Create a future, auditable, source-isolated path to ingest settled broker-origin paper fills and compare Gateway's persisted copy with a separately retrieved broker activity export. The comparator measures ingestion consistency, not independent execution quality.

## Current boundary

`paper_portfolio.py` and `fill_simulator.py` create simulated fills. They are not broker-origin evidence. `services/reconciliation.py` is a stub. Existing sample scripts/fixtures do not establish real broker activity. Live routes remain unmounted and direct broker order placement is disabled pending durable intent/recovery. No broker requests or orders are authorized for this design step.

## Required data separation

Keep three distinct stores/facts:

1. **Simulated portfolio ledger** — existing simulator-generated orders/fills/positions/cash.
2. **Broker order intent/state** — durable record of requested broker mutations and observed order state; no fill is implied by intent or order status.
3. **Broker-origin fill ledger** — append-only facts imported from broker activity/fill evidence.

No simulator row may be copied, relabelled or used to satisfy the broker-fill gate. Broker fill corrections/revisions are new linked facts, never silent mutation of prior evidence.

## Ingestion design (requires separate approval before implementation)

- Ingest only an explicitly configured broker-paper origin, exact paper host, and non-secret account identifier. Read-only API operations only. No order placement or cancellation from ingestion.
- Append stable activity IDs and associated broker order/client IDs, symbol, side, executed quantity, execution price, source-provided execution timestamp (if present), activity creation timestamp, retrieval timestamp, source, and redacted provenance.
- Paginate completely with the provider's documented pagination token. Persist retrieval manifest, response/page hashes, query interval, pagination completeness and cursor evidence. Duplicate IDs are idempotent; conflicting duplicate facts are flagged for review rather than overwritten.
- Keep `activity_created_at` distinct from execution time. Time-window acceptance uses the field actually supported by source filters and records the semantics.
- Never expose broker credentials, token-bearing URLs, account secrets or raw provider exception contents in stored manifests/logs.

## Comparator contract (provisional; freeze only after a reviewed real sample)

- Inputs are two separate UTF-8 JSON snapshots: (a) local broker-origin ingestion ledger export and (b) separately retrieved broker `FILL` activities. Both have Alpaca as source origin; comparison proves ingestion completeness/consistency, not independent execution quality.
- Manifest includes schema version, source origin/retrieval path, evidence kind (`real` or `synthetic`), environment `paper`, non-secret account ID, distinct snapshot/retrieval IDs, capture time, closed UTC comparison window, settlement margin, settled-through time, completeness and pagination metadata, query metadata and raw page SHA-256 hashes.
- A fill includes stable activity ID, order/client IDs, symbol, side, quantity and price as exact decimal strings, execution timestamp and activity creation timestamp.
- Match stable activity ID first. Cross-check order/client IDs. Compare symbol/side exactly, quantity/price exactly unless a future reviewed sample justifies explicit tolerance. Compare timestamps only when their semantics are equivalent and any tolerance is explicit and recorded.
- Use unique ID union as denominator. Each orphan, conflicting duplicate, recoverably malformed row or field discrepancy makes that ID a mismatch exactly once; record every field diagnostic. Exact duplicate identical records are deduplicated and reported without extra denominator.
- Missing/invalid structural metadata, unrecoverable identity, duplicate snapshot/retrieval, incomplete retrieval, un-settled window, synthetic evidence, unsupported timestamp semantics or zero denominator cannot PASS and report `INSUFFICIENT_EVIDENCE`. Malformed input is a tool error, not silently dropped.
- Three outcomes: `PASS`, `FAIL`, `INSUFFICIENT_EVIDENCE`. A real, complete, settled sample can PASS only with at least 1,000 unique fills and mismatch ratio strictly below 0.1%. A nonzero sample at or above the 0.1% threshold is FAIL even if undersized; a below-threshold sample under 1,000 is insufficient. Fixtures can never yield real PASS.
- CLI exit code proposal: 0 PASS, 1 FAIL, 3 insufficient evidence, 2 malformed input/tool error. Output includes denominator, both orphan directions, duplicates, per-field discrepancies, tolerances, window/settlement, source/provenance hashes, evidence kind and outcome.

## Rollout gates

- **Gate A — design freeze:** validate provisional schema/fields/window semantics against a real, sanitized sample obtained by an explicitly approved, read-only process; conduct schema/security review.
- **Gate B — ingestion implementation:** add broker-origin ledger and tests for pagination, idempotency, revisions, completeness, source isolation, redaction and paper-origin enforcement. No orders sent.
- **Gate C — comparator:** implement fixture comparator and prove all threshold/edge cases. Synthetic fixtures cannot claim a real pass.
- **Gate D — soak harness:** separate design/review and explicit user opt-in, durable order intent/recovery, identity/ownership, independent risk controls, fixed small paper limits, clear stop and audit requirements. Not part of this change; cannot be inferred from Gate A/B/C.
- **Evidence gate:** only after validated ingestion plus separately authorized and completed soak may the 1,000 settled paper-fill / <0.1% criterion be evaluated. The current Phase 4 remains not verified and Phase 5 remains blocked until then.

## Tests and threat cases

- Broker-origin facts cannot be inserted through manual journal/API input or sourced from the simulator.
- Pagination completeness, duplicate IDs, conflicting revisions, repeated retrieval, malformed/missing IDs, timestamp ambiguity, incomplete settlement and raw hash verification.
- Exact match, both orphan directions, per-field mismatches, decimal exactness and threshold boundaries (including 1/1,000 fails; 1/1,001 is below 0.1%; n<1,000 below threshold remains insufficient).
- Synthetic input never passes; malformed input never disappears; same retrieval cannot masquerade as independent acquisition.
- No credential or endpoint query secret in public output, logs or evidence artifact.
- Confirm zero broker writes/network order calls under all tests.
