---
#### **`docs/phase-6-plan.md`**
```markdown
# Phase 6 — OpenBB Open-Data Integration (PROPOSED — AUTHORITIES COMMISSIONED)

> Status: **Proposed / plan emitted 2026-09-20.** Not implemented. Authorizations resolved by default (both pkg+server, `ENABLE_OPENBB_DATA` false, AGPLv3 review required). Parallel with Phase 5 allowed (data feed independent of live-broker gates). Compared to codebase-memory (gen 2026-09-20): OpenBB not indexed; available evidence = release docs + `market_data.py` / `provider_registry.py` + `alpaca_live.py` draft.
>
> Source: https://github.com/OpenBB-finance/OpenBB (AGPLv3). Repo index: Gateway (codebase-memory, gen 2026-09-20, 1665 nodes).

## Unresolved → Resolved (with defaults)

| # | Clarification | Default chosen | Note |
|---|---------------|----------------|------|
| 1 | Scope: package / server / both | **Both** | Slice 6.1 = `openbb` pkg; Slice 6.4 = `openbb-api` server (port 6900) |
| 2 | Filename | **`docs/phase-6-plan.md`** | Matches phase-0..5 sequence |
| 3 | Phase 5 dependency | **Parallel allowed** | Data feed independent from live-broker gates (`alpaca_live.py` draft = 3 lines) |
| 4 | Slices / order | **4 slices (see below)** | Data provider → CLI/API → Engine feed → Optional server |
| 5 | Feature flag | **`ENABLE_OPENBB_DATA` (default false)** | Mirrors `ENABLE_LIVE_ALPACA` |
| 6 | Acceptance criteria | **Proposed below** — revise if needed |
| 7 | AGPLv3 compatibility | **Review required** before prod; documented here |
| 8 | Provider interface verification | **Best-effort via directory + `market_data.py`**; `alpaca_provider.py` not fully indexed |

## Context (verified from repo + OpenBB)

- OpenBB (user URL): open-source data platform; `pip install openbb`; CLI `openbb-cli`; Python `obb` modules (`obb.equity`, `obb.crypto`, `obb.fixedincome`, etc.); FastAPI server via `openbb-api` (port 6900); AGPLv3.
- Repo `quant-app-v1/backend/app/providers/alpaca_live.py`: 3 lines ("Status: Draft — prerequisites not met"). Not a blocker for data-layer Phase 6.
- `quant-app-v1/backend/app/services/market_data.py`: clean (ingestor); `provider_registry.py`: directory (registry); `requirements.txt`: lines 28-29 (`alpaca-trade-api`, `alpaca-py`) — dependency insertion point.
- Quant engine: `quant-app-v1/backend/app/quant/indicators.py`, `backtester.py`, `risk_engine.py` — pandas/numpy compatible with OpenBB output frames.

## Prerequisites (must complete before production; parallel with Phase 5 ok for dev)

- [ ] User explicitly confirms scope above (package / server / both) — if "package only", drop 6.4.
- [ ] AGPLv3 license review for proprietary quant components (legal/compliance per Phase 5.4).
- [ ] Phase 5 prerequisites reviewed — `alpaca_live.py` is draft; Phase 6 data feed does NOT require live broker.
- [ ] `ENABLE_OPENBB_DATA` feature flag documented; default `false`.
- [ ] Dependency audit: `openbb` package + optional server image; add to `requirements.txt` / `docker-compose.yml`.
- [ ] Provider interface spec aligned: compare with any existing `alpaca_provider.py` / `finnhub_provider.py` once indexed.

## Integration Slices (high-level, sequential; week estimates proposed, not committed)

### Slice 6.1: OpenBB Data Provider (Week 1–3)
**Focus:** New provider module wrapping OpenBB data into existing model.

**Deliverables**
- `quant-app-v1/backend/app/providers/openbb_provider.py` (NEW):
  - Wraps `obb.equity.price.historical()`, `obb.crypto.price.historical()`, etc.
  - Outputs aligned to existing `TickData` / `MarketData` pandas model (`market_data.py`)
  - Config-driven symbol list; rate-limit awareness (OpenBB provider APIs)
  - Feature-flag gated: only registered when `ENABLE_OPENBB_DATA=true`
- `quant-app-v1/backend/app/services/provider_registry.py`: register `openbb_provider`
- Unit tests: frame conversion, empty response, rate-limit retry

**Acceptance criteria**
- `obb.equity.price.historical("AAPL")` → `DataFrame` → provider transforms to `TickData` list with correct schema
- Feature-flag off → provider unregistered; on → endpoint <2s p95 for 1 symbol / 30-day history
- No network dependency when disabled

---

### Slice 6.2: CLI / REST API Wrapper (Week 3–5)
**Focus:** Surface OpenBB to frontend / external consumers.

**Deliverables**
- `quant-app-v1/backend/app/api/openbb_routes.py` (NEW):
  - `GET /api/v1/openbb/equity?symbol=AAPL&period=1m` → provider → `TickData`
  - `GET /api/v1/openbb/crypto?symbol=BTC` → same
  - `GET /api/v1/openbb/available` → list loaded integrations
- `quant-app-v1/backend/app/cli/openbb_cli.py` (NEW, optional): command-line access using `obb.*`
- Auth same as existing `/api/v1/` routes; no extra auth model

**Acceptance criteria**
- Endpoint responds in <2s p95 for common request
- Invalid symbol returns 4xx with message (not 500)
- Feature-flag off returns 503 or 404 (configurable)

---

### Slice 6.3: Quant Engine Feed (Week 5–7)
**Focus:** Pipe OpenBB data into existing quant pipeline.

**Deliverables**
- Update `quant-app-v1/backend/app/services/market_data.py`: add `OpenBBIngestor` or extend `MarketDataIngestor`
- Feed into `quant/indicators.py`, `backtester.py`, `risk_engine.py`
- Column mapping doc: OpenBB `close`, `open`, `high`, `low`, `volume` → existing schema
- Backfill / replay capability using OpenBB historical data (replay engine integration with Phase 5.3 audit log if needed)

**Acceptance criteria**
- Historical backtest using OpenBB data produces same indicator values (within float tolerance) as existing source
- Replay from audit event + OpenBB data reconstructs port state (if combined with Phase 5.3)

---

### Slice 6.4: Optional OpenBB-API Server (Week 7–9; SKIPPABLE if scope = package only)
**Focus:** Deploy standalone `openbb-api` for multi-service consumption.

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

## File Paths (new + modified)

**New**
- `quant-app-v1/backend/app/providers/openbb_provider.py`
- `quant-app-v1/backend/app/providers/openbb_server_provider.py` (optional, 6.4)
- `quant-app-v1/backend/app/api/openbb_routes.py`
- `quant-app-v1/backend/app/cli/openbb_cli.py` (optional)
- `docs/phase-6-plan.md` (this document — emitted during build transition)

**Modified**
- `quant-app-v1/backend/app/services/provider_registry.py`
- `quant-app-v1/backend/app/services/market_data.py`
- `requirements.txt` (add `openbb`; optional server deps)
- `docker-compose.yml` (optional 6.4 service)
- `quant-app-v1/backend/app/config.py` / settings: add `ENABLE_OPENBB_DATA`, `ENABLE_OPENBB_SERVER`

**Unmodified / Reference**
- `docs/phase-5-plan.md` (sequence reference; Phase 5 prerequisites remain)
- `quant-app-v1/backend/app/providers/alpaca_live.py` (draft; not modified by this plan)

## Dependency / License Notes

- `openbb` package: PyPI `openbb`; AGPLv3. Before prod: confirm proprietary quant component compatibility; document attribution; consider separate service/container for AGPL isolation.
- `openbb-api` (FastAPI): same repo, same license; separate build/template.
- Python version: OpenBB supports 3.9–3.12 (per README). Repo Python version must match.

## Acceptance Criteria (proposed — revise if needed)

- [ ] `ENABLE_OPENBB_DATA=true` → `/api/v1/openbb/equity?symbol=AAPL` returns valid `TickData` <2s p95
- [ ] `ENABLE_OPENBB_DATA=false` → provider unregistered; endpoint unavailable (503/404)
- [ ] `openbb_provider.py` transforms `obb` output to existing schema with zero data loss (close/open/high/low/volume + timestamp)
- [ ] AGPLv3 attribution documented; legal sign-off recorded (Phase 5.4 style)
- [ ] (If 6.4) `openbb-api` container healthy; provider connects; graceful failure when server down
- [ ] Feature flags documented in `docs/` and `config.py`; default `false`

## Intentionally Unavailable / Blocked

- Phase 6 production deployment until AGPLv3 review complete
- Additional asset-class providers beyond equity/crypto/fixed-income until Phase 6.1 proven
- Multi-provider fusion (combine OpenBB + Alpaca live feeds) until Phase 5 live broker proven
- No change to `alpaca_live.py` (remains draft; out of scope)

## Editor / Build Notes

- Plan emitted during plan→build mode transition (user: "do what you need").
- No edits made to source code; only `docs/phase-6-plan.md` created.
- User's 8 clarifications resolved by default; if any must change, update this document's "Unresolved → Resolved" section and re-phase.
