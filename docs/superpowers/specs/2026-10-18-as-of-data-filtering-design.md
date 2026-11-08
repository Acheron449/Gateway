# As-Of Data Clock and Historical Filtering — Design

## Goal

Establish a server-enforced UTC `as_of` boundary for historical market data and timestamped context so replay/backtest consumers cannot receive records later than their requested simulation time.

## Scope

### In scope

- Add an optional `as_of` datetime argument to historical provider requests and the relevant API query parameters.
- Normalize supplied datetimes to UTC and reject naive or malformed values at API boundaries rather than guessing a timezone.
- Enforce the cutoff in the provider adapter and again in the service/API normalization path, including when data came from a fallback provider or was resampled.
- Apply the same upper-bound semantics to timestamped news, quote, and existing analysis/history consumers where those records are available in the current provider contracts.
- For requests with `as_of`, discard records with missing, invalid, or unparseable event timestamps; do not allow unknown timestamps to bypass the time boundary.
- Preserve existing behavior when `as_of` is omitted.
- Add deterministic tests for timestamps before, exactly equal to, after the cutoff, and absent/invalid timestamps.

### Deferred

- Replay sessions, isolated replay portfolios, playback controls, trade entry/fill simulation, and CSV/strategy backtests.
- Fundamentals filtering because no fundamentals provider or API endpoint currently exists.
- Historical quote reconstruction: the current providers expose current quote snapshots rather than historical quote series. A current quote can be excluded when its timestamp is after `as_of`, but cannot be reconstructed for an earlier time.
- Frontend controls for choosing `as_of`.
- Changes to provider history-depth limits and vendor entitlement policy.

## Data contract

- `as_of` is an optional timezone-aware ISO-8601 datetime accepted by the public historical data endpoints and passed as an aware UTC datetime into provider methods.
- Historical provider methods accept a keyword-only optional `as_of` value, preserving positional compatibility for existing `instrument/symbol`, `interval`, and `range` callers.
- Returned candle records retain existing field names. Their `time`/timestamp is interpreted as Unix seconds when numeric and as an ISO-8601 datetime otherwise. With `as_of` set, a row is admissible only when its parsed timestamp is at or before the UTC cutoff.
- News records are admitted only when their published/event timestamp is parseable and `published_at <= as_of`. Quote snapshots must expose a timestamp/provenance `data_time`; with an `as_of` request, a missing timestamp is rejected rather than treated as historical.
- Invalid or naive `as_of` requests receive HTTP 422. Valid `as_of` requests do not silently return future or un-timestamped records.

## Architecture and behavior

1. Keep provider selection and fallback behavior intact, but propagate the same cutoff to each candidate source.
2. Provider adapters pass `as_of` upstream where the provider supports an end-date parameter and independently filter normalized results before returning. Adapters that cannot constrain upstream requests still filter locally.
3. Central filtering helpers parse UTC instants and filter all rows after acquisition. API history applies the filter after fallback resolution and after resampling so derived bars cannot extend beyond the cutoff.
4. Timestamped news and quote routes apply the same cutoff before serialization. Where a provider returns current-only quote data without trustworthy event time, an `as_of` request returns no quote rather than mislabeling it.
5. Analysis/history consumers must compute indicators only from already-filtered OHLCV rows. If too few rows remain, preserve their existing empty/error behavior; do not backfill with post-cutoff data.
6. Requests that omit `as_of` remain backward compatible and follow current provider behavior.

## Integration boundaries

- Canonical market-data adapter interface: `quant-app-v1/backend/app/providers/base.py`.
- Concrete historical providers: Yahoo Finance, Alpaca, Finnhub, TradingView, AllTick, CCXT, and London Strategic Edge, subject to each adapter's existing timestamp format and API capability. OpenBB is not a historical source; its compatibility/history endpoints were removed, and historical requests must use the existing providers.
- Main chart/history API and its fallback/resampling path: `quant-app-v1/backend/app/api/main.py`.
- OHLCV analysis/metadata paths: `quant-app-v1/backend/app/services/market_data.py`, analysis and stock routes.
- Timestamped context routes: `quant-app-v1/backend/app/api/v1/news.py` and provider records.
- Existing provider tests plus focused API tests in `quant-app-v1/backend/tests/`.

## Error handling and compatibility

- Validate `as_of` at FastAPI request boundaries; malformed and naive datetimes fail with 422.
- A failed provider remains eligible for current fallback behavior, but every fallback receives and enforces the exact same cutoff.
- Do not turn provider failures into valid empty market data if the current route reports an upstream failure; retain its established behavior.
- Never substitute the wall clock for a missing record timestamp when a cutoff exists.
- No dependency additions are required; use Python's datetime/zoneinfo and existing Pydantic/FastAPI types.

## Tests and acceptance criteria

- Unit tests prove records at the cutoff are retained, records after it are rejected, and records with missing/invalid timestamps are rejected when `as_of` is set.
- Provider tests prove adapter-level filtering and upstream end-time propagation where supported.
- API tests prove invalid/naive cutoff input returns 422 and that all history fallbacks/resampling return only bars with timestamp `<= as_of`.
- Analysis tests prove indicators receive only filtered bars and do not see later data.
- News/quote tests prove timestamped future data is excluded and unknown-time data is not passed off as historical.
- Regression tests prove omitted `as_of` preserves the current response behavior.
- Run focused backend tests for all modified providers/routes and the complete backend test suite if time permits; report any unavailable dependencies or environment constraints rather than counting them as passes.

## Limitations and risks

- Provider timestamps may have differing precision and semantics (bar start vs bar end); acceptance uses the timestamp represented in the current normalized record. Later execution-engine design must define bar-close/fill semantics explicitly.
- This phase prevents timestamp-based look-ahead leakage but does not guarantee historical vendor data is immutable or prevent LLM training-data leakage.
- A provider may ignore requested end-time bounds; local filtering remains mandatory.
- Existing endpoint consumers must remain compatible when the optional parameter is absent.
