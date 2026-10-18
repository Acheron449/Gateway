---
#### **`docs/phase-6-plan.md`**
```markdown
# Phase 6 — OpenBB Open-Data Integration (PROPOSED — AUTHORITIES COMMISSIONED)

> Status: **Historical OHLCV support is retired.** OpenBB is retained for quote/news/calendar context only; the old history compatibility layer is not used. Historical requests use existing providers: Yahoo Finance, Alpaca, Finnhub, TradingView, AllTick, CCXT, or London Strategic Edge. Quote/news/calendar context features remain feature-gated behind `ENABLE_OPENBB_DATA=false` and `ENABLE_OPENBB_SERVER=false`; AGPLv3 review is required before production use.
>
> Source: https://github.com/OpenBB-finance/OpenBB (AGPLv3). Repo index: Gateway (codebase-memory, gen 2026-09-20, 1665 nodes).

## Unresolved → Resolved (with defaults)

| # | Clarification | Default chosen | Note |
|---|---------------|----------------|------|
| 1 | Scope: package / server / both | **Context only** | Quote/news/calendar context retained; history is not supported |
| 2 | Filename | **`docs/phase-6-plan.md`** | Matches phase-0..5 sequence |
| 3 | Phase 5 dependency | **Parallel allowed** | Data feed independent from live-broker gates (`alpaca_live.py` draft = 3 lines) |
| 4 | Slices / order | **3 retained slices (see below)** | Context provider → context API/CLI → Optional context server |
| 5 | Feature flag | **`ENABLE_OPENBB_DATA` (default false)** | Mirrors `ENABLE_LIVE_ALPACA` |
| 6 | Acceptance criteria | **Proposed below** — revise if needed |
| 7 | AGPLv3 compatibility | **Review required** before prod; documented here |
| 8 | Provider interface verification | **Best-effort via directory + `market_data.py`**; `alpaca_provider.py` not fully indexed |

## Context (verified from repo + OpenBB)

- OpenBB context adapters may provide quote, news, and calendar data. Its historical OHLCV compatibility layer is obsolete and is excluded; chart/history retrieval uses the existing provider adapters. The optional SDK/server features remain feature-gated.
- Repo `quant-app-v1/backend/app/providers/alpaca_live.py`: 3 lines ("Status: Draft — prerequisites not met"). Not a blocker for data-layer Phase 6.
- Historical data flows through the selectable provider history endpoint and the provider registry; OpenBB is not included in that chain.
- Quant engine historical prices continue to use the configured providers in the canonical history contract; OpenBB output is not used for historical bars.

## Prerequisites (must complete before production; parallel with Phase 5 ok for dev)

- [ ] Confirm whether the optional OpenBB context server (slice 6.4) is in scope; it does not serve historical bars.
- [ ] AGPLv3 license review for proprietary quant components (legal/compliance per Phase 5.4).
- [ ] Phase 5 prerequisites reviewed before any live-broker integration; historical context provider work does not require live broker access.
- [ ] `ENABLE_OPENBB_DATA` feature flag documented; default `false`.
- [ ] Dependency audit: OpenBB context package and optional server image; add only if retained context integration requires them.
- [ ] Provider interface spec aligned: compare with any existing `alpaca_provider.py` / `finnhub_provider.py` once indexed.

## Integration Slices (high-level, sequential; week estimates proposed, not committed)

### Slice 6.1: OpenBB Context Provider (Week 1–3)
**Focus:** OpenBB context integration only. OpenBB historical OHLCV adapter support was removed; historical prices come from the existing chart/history providers.

**Deliverables**
- Retain the existing OpenBB quote/news/calendar context adapter and its feature flag.
- Do not register OpenBB as a historical `MarketDataProvider` source.
- Unit tests should cover only retained context behavior.

**Acceptance criteria**
- Historical OHLCV routes and provider selection do not call OpenBB.
- Historical data is retrieved from the existing selectable providers.
- OpenBB context features remain disabled by default and make no network request when disabled.

---

### Slice 6.2: Context CLI / REST API Wrapper (Week 3–5)
**Focus:** Surface retained OpenBB context data to frontend / external consumers; no equity/crypto history endpoints.

**Deliverables**
- Retained API routes: `/openbb/quote`, `/openbb/news`, `/openbb/calendar`, and `/openbb/available`.
- Optional CLI commands cover quote, news, calendar, and integration listing only; equity/crypto history commands are removed.
- Auth follows the existing API conventions; no separate auth model.

**Acceptance criteria**
- Endpoint responds in <2s p95 for common request
- Invalid symbol returns 4xx with message (not 500)
- Feature-flag off returns 503 or 404 (configurable)

---

### Slice 6.3: Quant Engine Feed — Retired

OpenBB is not a source for the chart, analysis, or backtest historical-data pipeline. `OpenBBIngestor`, `fetch_ohlcv_openbb`, and the OpenBB history methods/routes/CLI commands are removed. Analysis and backtests use the existing provider history contract and configured sources instead. Do not restore the obsolete compatibility layer.

---

### Slice 6.4: Optional OpenBB Context Server (Week 7–9; optional)
**Focus:** Deploy standalone `openbb-api` for quote/news/calendar context only; it is not a historical data source.

**Deliverables**
- `docker-compose.yml` addition: `openbb-api` service (port 6900; image / build from OpenBB repo)
- `quant-app-v1/backend/app/providers/openbb_server_provider.py` (optional): connects via `httpx` to `localhost:6900`
- Network isolation: backend → server via internal Docker network; server not exposed externally without gateway
- Dependency note: `openbb-api` requires `openbb` package + FastAPI/uvicorn

**Acceptance criteria**
- `curl http://openbb-api:6900/` responds; `/docs` shows OpenBB endpoints
- Provider fails gracefully on server down; retry with backoff
- Feature-flag `ENABLE_OPENBB_SERVER` (default false) controls usage

---

## Retained OpenBB Context Files

- `quant-app-v1/backend/app/providers/openbb_provider.py` — quote/news/calendar context.
- `quant-app-v1/backend/app/providers/openbb_server_provider.py` — optional quote/news/calendar context server.
- `quant-app-v1/backend/app/api/openbb_routes.py` — quote/news/calendar/available routes only.
- `quant-app-v1/backend/app/cli/openbb_cli.py` — quote/news/calendar/available commands only.

Historical adapters, routes, CLI commands, and ingestion helpers are removed; do not add them back.

**Unmodified / Reference**
- `docs/phase-5-plan.md` (sequence reference; Phase 5 prerequisites remain)
- `quant-app-v1/backend/app/providers/alpaca_live.py` (draft; not modified by this plan)

## Dependency / License Notes

- `openbb` package: PyPI `openbb`; AGPLv3. Before prod: confirm proprietary quant component compatibility; document attribution; consider separate service/container for AGPL isolation.
- `openbb-api` (FastAPI): same repo, same license; separate build/template.
- Python version: OpenBB supports 3.9–3.12 (per README). Repo Python version must match.

## Acceptance Criteria (proposed — revise if needed)

- [ ] With `ENABLE_OPENBB_DATA=false`, retained context routes respond unavailable without network access.
- [ ] AGPLv3 attribution documented; legal sign-off recorded (Phase 5.4 style)
- [ ] (If context server is enabled) the context service connects and fails gracefully when unavailable.
- [ ] Feature flags documented in `docs/` and `config.py`; default `false`.

## Intentionally Unavailable / Blocked

- Phase 6 production use until AGPLv3 review complete
- OpenBB historical OHLCV retrieval; use existing history providers instead
- Historical backtesting / replay using OpenBB data
- Multi-provider fusion (combine OpenBB + Alpaca live feeds) until Phase 5 live broker proven
- No change to `alpaca_live.py` (remains draft; out of scope)

## Editor / Build Notes

- Historical OHLCV support is explicitly excluded from the retained OpenBB context integration; source selection uses existing historical providers.
- Implementation status was reconciled with the provider history path on 2026-10-18.
- The historical scope decision supersedes earlier proposed OpenBB history deliverables in this plan.
Priority link: see docs/phase-5-prerequisites.md (priority 6)
