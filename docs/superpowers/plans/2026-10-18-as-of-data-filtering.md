# As-Of Data Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional, server-enforced UTC `as_of` cutoffs for provider history and timestamped API context without changing requests that omit the cutoff.

**Architecture:** Introduce shared UTC timestamp parsing/filter helpers and extend the canonical provider history contract with keyword-only `as_of`. Propagate the cutoff through existing history providers (excluding OpenBB) and history API fallback/resampling paths, then apply it to analysis and the news/quote context routes where timestamped records are available. Tests start with the helper/API contracts, then cover adapters and consumers.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, pandas, pytest, httpx, existing market-data providers.

**Spec:** [docs/superpowers/specs/2026-10-18-as-of-data-filtering-design.md](../specs/2026-10-18-as-of-data-filtering-design.md)

## Global Constraints

- `as_of` is optional and timezone-aware; invalid or naive values return HTTP 422.
- Preserve existing behavior when `as_of` is omitted.
- Provider history methods accept keyword-only optional `as_of` without changing existing positional callers.
- Include only records with parseable event timestamps `<= as_of`; unknown timestamps do not qualify when cutoff exists.
- Apply cutoff again after provider fallback and chart resampling; no dependency addition.
- Current-only quotes cannot be reconstructed historically; reject them for cutoff requests unless reliable event time is present.

## Review Focus

- Numeric epochs vs ISO timestamps (including `Z` and offset datetimes): unit and adapter tests assert same UTC boundary.
- Naive and malformed cutoff query values: API tests assert 422.
- Missing or invalid row timestamps: helper and API tests assert exclusion only for cutoff mode; no-cutoff behavior remains intact.
- Fallback and resampling: chart endpoint tests inject future bars at the fallback source and assert no returned bar exceeds cutoff.
- Stale/current quote or headline context with absent timestamp: news/quote tests prove it is rejected when cutoff is supplied.

---

## File map

- Create `quant-app-v1/backend/app/services/as_of.py`: UTC normalization, timestamp parsing, row filtering.
- Modify `quant-app-v1/backend/app/providers/base.py`: canonical `history(..., *, as_of=None)` signature.
- Modify every history adapter under `quant-app-v1/backend/app/providers/`: Yahoo, Alpaca, Finnhub, TradingView, AllTick, CCXT, and LSE; propagate upstream end bounds where supported and filter locally. OpenBB is not a historical provider.
- Modify `quant-app-v1/backend/app/api/main.py`: chart sync fetches, adapter dispatch, CCXT fallback, `/history/{ticker}` and `/market/{ticker}/history` query contract, post-resample filter.
- Modify `quant-app-v1/backend/app/services/market_data.py`, `api/v1/analysis.py`, and `api/v1/stocks.py`: cutoff-aware OHLCV and indicator/metadata consumers.
- Modify `quant-app-v1/backend/app/api/v1/news.py` and `services/news_service.py` plus relevant provider methods: news cutoff and quote event-time gate.
- Add `quant-app-v1/backend/tests/test_as_of.py` for shared helper and API behavior; extend provider-specific test files for adapter parameters/filters.

Run the commands below from `quant-app-v1/backend`.

## Task 1: UTC timestamp helper and contract tests

**Interfaces:**
- Produces `normalize_as_of(value: datetime | None) -> datetime | None`, `parse_data_timestamp(value: Any) -> datetime | None`, `filter_timestamped_rows(rows, *, as_of, timestamp_keys=("time", "timestamp")) -> list[dict[str, Any]]`, and `is_at_or_before(value, as_of) -> bool` in `app.services.as_of`.
- `parse_data_timestamp` treats numeric values as Unix seconds, parses ISO-8601 including `Z`, treats timezone-naive data timestamps as invalid, and normalizes valid results to UTC.
- `normalize_as_of` rejects naive datetimes with `ValueError`; FastAPI query validation will convert bad input to HTTP 422.

- [x] **Step 1: Add helper tests** in `tests/test_as_of.py` for UTC offsets, numeric seconds, ISO `Z`, equality inclusion, future exclusion, absent/invalid timestamps, and no-cutoff identity behavior.
- [x] **Step 2: Run `pytest tests/test_as_of.py -q`**; expected failure because helper module does not exist.
- [x] **Step 3: Implement helper interfaces** in `app/services/as_of.py`; prefer aware UTC comparison and stable record order.
- [x] **Step 4: Re-run `pytest tests/test_as_of.py -q`**; expected all helper cases pass.

## Task 2: Propagate cutoff through historical provider contract

**Consumes:** Task 1 helpers.
**Produces:** Every existing historical `MarketDataProvider.history` implementation accepts `*, as_of: datetime | None = None`; returned history contains only timestamped records at or before cutoff when set. OpenBB is excluded from historical retrieval.

- [x] **Step 1: Add parameterization tests** for provider adapters (Yahoo, Alpaca, Finnhub, TradingView, AllTick, CCXT, LSE) asserting future rows are removed, equal cutoff rows remain, upstream end bounds use `as_of` when provider supports them, and no-cutoff calls preserve results.
- [x] **Step 2: Run the focused adapter tests** and verify they fail against current signatures/behavior.
- [x] **Step 3: Extend `MarketDataProvider.history` and each listed adapter** with keyword-only `as_of`; pass provider-specific end timestamps/ranges when supported; apply shared local filtering before returning. Preserve current exception/fallback contracts.
- [x] **Step 4: Run adapter tests and existing provider tests**: `pytest tests/test_as_of.py tests/test_phase2_provider_safety.py tests/test_yahoo_calendar.py tests/test_lse_provider.py -q`.

## Task 3: Chart API fallback and resampling

**Consumes:** Task 1 helpers and Task 2 provider signature.
**Produces:** `/history/{ticker}` and `/market/{ticker}/history` accept optional aware `as_of`; all returned candles are filtered after fallback and resampling. OpenBB has no historical-data routes.

- [x] **Step 1: Add API tests** that patch each chart source/fallback to return before/equal/after/missing timestamps; assert `max(time) <= as_of`, provider/fallback sees exact UTC cutoff, naive/malformed query returns 422, and omitted cutoff is unchanged.
- [x] **Step 2: Run the new history API tests** and verify failure on missing `as_of` support/future rows.
- [x] **Step 3: Thread cutoff through synchronous Yahoo/Alpaca history fetches, async provider dispatcher, and CCXT fallback**; clamp request end times; filter provider rows before and after `_resample_candles`.
- [x] **Step 4: Run history tests plus `tests/test_phase0_safety.py tests/test_lse_provider.py tests/test_data_sources.py -q`**.

## Task 4: Analysis, news, calendar, and quote context

**Consumes:** Task 1 helper and Task 2 provider contract.
**Produces:** Existing analysis/history consumers compute from bounded bars; timestamped news and calendar context supports optional `as_of`; current quote snapshots without an event timestamp are unavailable for historical cutoff queries.

- [x] **Step 1: Add consumer tests** proving analysis calculation receives only rows `<= as_of`; history-backed metadata uses cutoff; future/missing-time news records are excluded; quote payloads without trustworthy `data_time` are unavailable under `as_of`; omitted cutoff still behaves as before.
- [x] **Step 2: Run consumer tests** and verify expected failures.
- [x] **Step 3: Add optional cutoff to `fetch_ohlcv`, `/analysis/{ticker}`, `/stocks/{ticker}/metadata`, `/news`, and `/quote/{symbol}` as supported. Filter before indicator calculations and before serialization. Make quote response explicitly unavailable (no fabricated historical value) if timestamp is missing or after cutoff. The retired OpenBB ingestor is not part of this flow.
- [x] **Step 4: Run focused consumer tests and related integration tests**: `pytest tests/test_as_of.py tests/test_integration.py tests/test_phase0_safety.py -q`.

## Task 5: Full verification and regression review

- [x] Run all backend tests from `quant-app-v1/backend`: `pytest -q` (attempted; collection blocked by existing Pydantic, optional dependency, vendored-test import, and SciPy binary issues; see final report).
- [x] Run `git diff --check` and inspect the full diff, confirming no changes to unrelated/unowned files.
- [x] Confirm all public callers without `as_of` retain their old signatures and response shapes, and every existing history adapter in scope filters both in isolation and through public API fallback/resampling; verify OpenBB is absent from historical source selection.
- [x] Report unavailable checks or provider-specific gaps explicitly; do not claim historical quote reconstruction.
