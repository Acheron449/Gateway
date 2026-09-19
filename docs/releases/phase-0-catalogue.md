# Phase 0 domain + catalogue slice

## User outcome

Symbol search and the instrument workspace are backed by a versioned, provence-carrying US-equities catalogue instead of a hard-coded list of six tickers. Every catalogue record answers "which snapshot produced this, when, and under what entitlement", and the frontend surfaces that provenance instead of raw payloads.

## Changes

- Added typed domain records (`app/models`) for `Instrument`, `Quote`, `Candle`, `NewsItem`, `EconomicEvent`, `Strategy`, `StrategyVersion`, `BacktestRun`, `Order`, `Fill`, `Position`, `Portfolio`, and a shared `Provenance` model. Domain `Order` records are paper-only, reject placeholder symbols/zero quantities, and forbid unknown fields.
- Added a versioned initial catalogue snapshot at `quant-app-v1/backend/data/instruments/catalogue_v1.json` (40 US equities/ETF, schema 1.0, catalogue 1.0.0) with `gateway-instrument-catalogue` provenance.
- Added `app/services/catalogue.py` (typed loader, symbol lookup, name/symbol search) and `GET /catalogue` + `GET /catalogue/search` endpoints.
- Replaced the hard-coded six-ticker `/stocks/search` with the catalogue; `/stocks/{ticker}/metadata` now returns catalogue fields, and unknown symbols return a clear 404 instead of a fabricated match.
- Frontend Scanner now queries `/catalogue/search`, renders typed instrument records, and shows the catalogue source/version. Added the previously missing `index.html` so `npm run build` works from a fresh checkout.
- Added GitHub Actions CI (`.github/workflows/ci.yml`) that installs backend dependencies, compiles the Python app, runs the test suite, and builds the frontend.
- Documented frontend+backend startup and test commands in `README.md`.

## Tests

`tests/test_phase0_catalogue.py` covers catalogue version/provenance, lookup + search (including unknown/blank queries), placeholder-symbol and live-mode rejection on domain orders, non-secret `/catalogue` output, the frozen `/stocks/search` shape, catalogue-backed metadata, unknown-symbol 404s, and paper-only health across all four environment profiles.

## Intentionally unavailable

Live execution, structured news/calendar providers, a licensed broad instrument reference, strategy approval, and durable user workspaces remain later roadmap increments. The catalogue is a free snapshot, not an exhaustive market listing; expanding it requires a licensed/permissioned data decision.

## Developer migration

No configuration change required. The catalogue loads automatically from `data/instruments/`; replace `catalogue_v1.json` snapshot only via a reviewed versioned-snapshot update.