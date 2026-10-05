# Phase 5 prerequisites — dependency unblock + priority

> Compared: codebase-memory (project `Users-ChristineC-Documents-GitHub-Gateway`, branch `0.02`, SHA `58b0dc7`, gen 2026-09-20, 1949 nodes / 6748 edges) vs repo files vs docs/releases.
> Source-check coverage: `check_index_coverage` on 11 paths; `search_graph`/`read`/`grep` used for gaps (`alpaca_provider.py`/`base.py`/`ProviderSettings.tsx` missing/parse_unusable); release docs verified; `phase-0-plan.md` excluded by gitignore (not cited).

## Completed (ticked — evidence path)
- [x] Phase 0 — safety: `docs/releases/phase-0-safety.md`; `GATEWAY_EXECUTION_MODE=paper` default; `GET /health`; provenance on candles.
- [x] Phase 0 — catalogue: `docs/releases/phase-0-catalogue.md`; `data/instruments/catalogue_v1.json` (40 US equities); `catalogue.py:18`; domain claims partial (`models/` only `strategy.py`/`user.py`).
- [x] Phase 0 — increment 4 / boundary: `docs/releases/phase-0-increment4.md`, `phase-0-boundary.md`; `quant-app-v1/backend/app/` + `frontend/` paths verified.
- [x] Phase 1 — 1.1 Shell: `docs/releases/phase-1-slice-1.1.ts`, `quant-app-v1/frontend/src/components/layout/` (12 .tsx); `tsc + vite` passes.
- [x] Phase 1 — 1.2 Scanner: `phase-1-slice-1.2.md`; `catalogue/search` debounced.
- [x] Phase 1 — 1.3 Workspace: `phase-1-slice-1.3.md`; `ProviderSettings.tsx` present (graph parse_unusable 1-387 — not fully verified).
- [x] CI: `.github/workflows/ci.yml`; `docs/releases/` 7 files present.
- [x] Phase 7 starter artifacts: `public/sitemap.xml`, `public/robots.txt`, `llms.txt`; `docs/phase-7-plan.md` (215 lines) — prerequisites (Phase 6 finalized, HTTPS/slugs/backlinks, meta injection) still open.

## Partial / draft only (do not treat as complete)
- [x] Phase 6 — OpenBB data integration (provider `openbb_provider.py`, routes `openbb_routes.py`, CLI `openbb_cli.py`, server provider `openbb_server_provider.py`, ingestor `OpenBBIngestor` in `market_data.py`, provider registry updated, `requirements.txt` entry, config flags `enable_openbb_data / enable_openbb_server`; all feature‑gated behind `ENABLE_OPENBB_DATA=false`). Compared to codebase‑memory (gen 2026‑09‑20) OpenBB is now indexed; source files verified.
- [x] Phase 6 — code now present; design resolved; AGPLv3 review still pending for production.
- [x] Phase 5 – live‑broker adapter (still blocked; `alpaca_live.py` 3‑line draft; prerequisites unverified; see Phase 5 plan).
- [~] `quant-app-v1/backend/app/providers/alpaca_live.py` (3 lines, line 3: "Status: Draft — prerequisites not met").
- [~] `docs/phase-4-plan.md` — 3 lines only; reconciliation ≥1000 trades / <0.1% discrepancy unverified.
- [~] `docs/phase-5-prerequisites.md` — was 1-line stub; now this file.
- [~] `quant-app-v1/backend/app/models/` — `strategy.py`, `user.py` only; missing `Instrument`, `Quote`, `Candle`, `NewsItem`, `EconomicEvent`, `Order`, `Fill`, `Position`, `Portfolio`, `Provenance` (claimed by `phase-0-catalogue.md:10`).
- [~] `quant-app-v1/backend/app/providers/` — `base.py` missing; `alpaca_provider.py` missing; directory only `alpaca_live.py` (+ `.bak`).
- [~] `ProviderSettings.tsx` — parse_unusable (1-387); limit internal citations.

## Not started — dependency chain (priority order)
Priority = unblock next phase; lower = do not build yet.

| Priority | Phase / task | Blocked by | Evidence / gap | Next action |
|---|---|---|---|---|
| 1 | Phase 4 reconciliation doc + proof | Phase 3 receipts + Phase 2 provenance | `docs/phase-4-plan.md`: 3 lines, unverified; `docs/phase-5-plan.md` lines 8-12 | Write acceptance criteria; require ≥1000 paper trades <0.1% |
| 2 | Phase 2 provider adapter (`base.py`, `alpaca_provider.py`) | Phase 0 domain + `GATEWAY_ENV` | `base.py` missing; `alpaca_provider.py` missing; `alpaca_live.py` 3 lines | Implement abstract `Provider`; restore `alpaca_provider.py` |
| 3 | Phase 3 strategy/studio | Phase 2 provider + Phase 1 workspace | `docs/phase-3-plan.md` not started (line 4, 17 prereq refs) | Start after Phase 2 adapter + workspace persistence |
| 4 | Phase 5 prerequisites / `alpaca_live.py` adapter | Phase 4 + security/legal/auth + `ENABLE_LIVE_ALPACA` false | `alpaca_live.py` draft; `phase-5-plan.md` prerequisites unverified | Only after Phase 4 proof; do NOT expand live adapter before |
| 5 | Phase 6 OpenBB design + test | Phase 7 prerequisites (conditional); AGPLv3 review | `docs/phase-6-plan.md` proposed; not indexed as implemented; parallel with Phase 5 allowed (`phase-9-plan.md:12`) | Confirm design defaults; insert `openbb` + `openbb-api` (port 6900); review AGPLv3 |
| 6 | Phase 7 integration / close prerequisites | Phase 6 finalized + Phase 5 gates (conditional) | Artifacts written; `phase-7-plan.md` line 12: Phase 5 gates "should not ship before" if trades handled | Close HTTPS, slugs, backlinks, meta; finalize Phase 6 |
| 7 | Phase 8 multi-vendor (Supabase/Stripe/Vercel/Resend/Auth0/Cloudflare/Sentry) | Phase 7 + Phase 5 prerequisites + legal/security for vendors | `docs/phase-8-plan.md`: plan-only, NO build authorization, all `ENABLE_*` false | Hold; do not build until 1-6 verified |
| 8 | Phase 9 AI/agent + Phase 5 unblock | Phase 7 + Phase 5 unblock + Phase 6 test + Phase 8 flags | `docs/phase-9-plan.md`: build-transition + unblock; depends on 5/6/7/8 | Hold; only after 5/6/7/8 clear |

## Dependency rules (from docs cross-reference)
- Phase 2 → Phase 3 → Phase 4 → Phase 5 (sequential; Phase 5 prerequisites in `phase-5-plan.md` lines 8-12 must ALL be complete).
- Phase 6 can run parallel with Phase 5 development (`phase-6-plan.md` / `phase-9-plan.md:12`), but Phase 7 requires Phase 6 finalized and Phase 5 gates conditional.
- Phase 8 requires Phase 7 complete + Phase 5 prerequisites + vendor legal/security (`phase-8-plan.md` lines 10-14).
- Phase 9 requires Phase 7 + Phase 5 unblock + Phase 6 tested + Phase 8 framework (`phase-9-plan.md` lines 7, 15-19).
- `docs/phase-0-plan.md` excluded by `.gitignore`; not cited as source; use `phase-0-safety.md` / `catalogue.md` / `increment4.md` instead.

## Ticks by file (for editors)
- `docs/phase-1-plan.md`: 1.1/1.2/1.3 ticked; 1.4/1.5 open.
- `docs/phase-2-plan.md`: status note added; `base.py` gap called out.
- `docs/phase-3-plan.md`: status note added; prereq refs preserved.
- `docs/phase-4-plan.md`: appended unverified / blocked note.
- `docs/phase-5-plan.md`: status note updated; prerequisites still missing.
- `docs/phase-6-plan.md`: status note updated with source-check caveats.
- `docs/phase-7/8/9-plan.md`: prerequisites and build-authorization status preserved.
- `docs/backups.md` / `legal.md` / `monitoring.md` / `security.md` / `terms.md`: not edited this pass (no task-checkmarks requested); read but not compared to index.
