# Phase 0 technical plan

## Boundary audit and active surface

The active product surface is `quant-app-v1/frontend`, a React/Vite client that consumes the FastAPI service in `quant-app-v1/backend/app`. `frontend/Gateway_app` is a legacy Flask surface and is not required for the React research workflow; it should be retained only while its authentication/landing routes are explicitly migrated. The FastAPI service currently mixes transport routes, provider access and simulation code, so Phase 0 separates configuration, provider provenance and execution guards before adding product features.

## Initial market decision

**US equities, paper trading only.** This is the narrowest credible first market because the existing history and streaming path already targets Alpaca equities and the search universe contains US tickers. FX remains a future adapter; no Forex Factory output may be represented as a current or complete market-news feed.

## Target domain and provider contracts

The next Phase 0 increments will define Pydantic domain records for `Instrument`, `Quote`, `Candle`, `NewsItem`, `EconomicEvent`, `Strategy`, `StrategyVersion`, `BacktestRun`, `Order`, `Fill`, and `Portfolio`. All market/event records will embed `Provenance` (`source`, `provider_version`, `fetched_at`, `data_time`, `coverage`, `delay_seconds`, `entitlement`).

**Status:** the typed domain records above are implemented in `app/models/__init__.py`. Provider adapters will expose typed methods such as `catalogue()`, `history(instrument, interval, range)`, `quote(instrument)`, and later `news()`/`calendar()`. Each returns normalized records plus provenance, never raw vendor payloads. An unavailable provider returns a typed unavailable state rather than substituted data.

## Independently reviewable Phase 0 pull requests

1. **Safety/configuration (done, in `docs/releases/phase-0-safety.md`):** environment profiles, non-secret capability health, paper-only guard, placeholder-order rejection, and provenance for the existing Alpaca history endpoint.
2. **Domain/catalogue (done, in `docs/releases/phase-0-catalogue.md`):** versioned US-equity instrument catalogue (`data/instruments/catalogue_v1.json`) and typed domain models (`app/models`) replacing the hard-coded six-symbol `/stocks/search`; `/catalogue` and `/catalogue/search` endpoints; frontend Scanner + missing `index.html`; basic CI (`/.github/workflows/ci.yml`).
3. **Application boundary:** isolate Flask routes and document React/FastAPI startup and migration ownership.
4. **Test/CI foundation:** unit tests for normalization, indicators, risk limits, backtest lifecycle and order guards; add format/type/test/build CI.

## Decisions required before later work

- Select and contract a licensed/permissioned US-equities news and economic-calendar provider, including redistribution, retention, latency and historical-snapshot rights.
- Choose authentication and durable workspace storage before implementing watchlists/layouts.
- Complete security, compliance and operational review before any live-execution scope is authorized. Live execution is intentionally unavailable.

## This increment’s acceptance criteria

- `GET /health` reports the profile and capabilities without credentials.
- Local, test, paper and production profiles all reject live execution.
- Empty, placeholder or invalid order fields are rejected before a provider is called.
- Every `GET /history/{ticker}` candle contains provider/freshness metadata.
