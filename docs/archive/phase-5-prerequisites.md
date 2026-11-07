# Phase 5 prerequisites — dependency unblock + priority

> Reconciled against current source, focused test runs, and the approved 2026-10-18 paper-safety plan. This checklist is a dependency tracker, not proof that downstream phase gates have passed.
>
> **Current Phase 5 decision:** broker paths are guarded and order placement fails closed; live routes are not mounted. Broker-order intent/recovery, broker-origin fill ingestion, comparator, real settled-fill evidence, security/legal/account ownership review, and explicit written authorization remain gated or unverified. The ≥1,000-fill / <0.1% gate is **insufficient evidence**.

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
- [x] Phase 6 — OpenBB quote/news/calendar context integration is present and feature-gated; OpenBB history endpoints, CLI history commands, adapter methods, and `OpenBBIngestor` have been removed. Historical market data uses Yahoo Finance, Alpaca, Finnhub, TradingView, AllTick, CCXT, or London Strategic Edge.
- [x] Phase 6 — code now present; design resolved; AGPLv3 review still pending for production.
- [x] Phase 5 safety boundary — `quant-app-v1/backend/app/services/alpaca_live.py` and `broker_service.py` validate the exact paper origin and fail closed on order placement; `/live` router is unmounted. This is safety hardening only, not a live adapter or evidence-gate completion (focused tests: 45 passed; see plan ledger).
- [~] Phase 5 — durable order-intent/recovery and broker-origin fill ingestion were not implemented; no independent reconciliation comparator or real settled-fill evidence exists. Phase 5 remains blocked.
- [~] `docs/phase-4-plan.md` — acceptance criterion and evidence gap documented; real reconciliation remains unverified.
- [x] `docs/phase-5-prerequisites.md` — dependency tracker reconciled to source/tests on 2026-10-18; downstream gates remain open.
- [~] Domain-model coverage remains incomplete relative to `phase-0-catalogue.md`; check current `models/__init__.py` before asserting any individual type absent.
- [x] `quant-app-v1/backend/app/providers/base.py` and `alpaca_provider.py` exist; the previous missing-file inventory was stale. Keep historical market-data providers distinct from broker-execution adapters in `app/services/`.
- [~] `ProviderSettings.tsx` — parse_unusable (1-387); limit internal citations.

## Not started — dependency chain (priority order)
Priority = unblock next phase; lower = do not build yet.

| Priority | Phase / task | Blocked by | Evidence / gap | Next action |
|---|---|---|---|---|
| 1 | Phase 4 comparator + real reconciliation proof | Independently sourced broker-fill ingestion and accepted evidence schema | `docs/phase-4-plan.md`: ≥1,000 settled real fills / <0.1% remains unverified; no broker-origin fill ledger/comparator | Design and implement broker-origin ingestion first; then independently reconcile settled real fills; simulator/sample rows do not count |
| 2 | Phase 2 completeness / provenance acceptance | Phase 0 domain and coverage requirements | Provider base and Alpaca market-data provider exist; complete licensed coverage, freshness/provenance and event snapshots not verified as a whole | Audit the Phase 2 acceptance criteria against current provider behavior; do not recreate existing adapters |
| 3 | Phase 3 completion | Phase 2 acceptance and full Phase 1 workspace | StrategySpec/version/hash capability exists, but full immutable reproducible backtest receipt + OOS/promote flow is not verified | Close missing slices and verify end-to-end receipts before Phase 4 gate |
| 4 | Phase 5 live eligibility | Phase 4 real evidence + security/legal + identity/ownership + written authorization | Adapter network guards exist, but order methods fail closed and `/live` is unmounted | Keep disabled; separately design durable broker-order intent/recovery and broker-origin fill ledger; no live expansion |
| 5 | Phase 6 production readiness | AGPLv3 review and retained-context acceptance | Quote/news/calendar scope retained; historical OHLCV retired; flags default false | Verify retained context behavior and complete legal review; no OpenBB history support |
| 6 | Phase 7 integration / close prerequisites | Phase 6 finalized; production host/access; conditional security/legal gates if trade handling | Starter artifacts exist; hosting-dependent HTTPS, slugs, backlinks, meta and crawl evidence remain open | Close the hosted-site acceptance criteria when hosting is authorized/configured |
| 7 | Phase 8 multi-vendor (Supabase/Stripe/Vercel/Resend/Auth0/Cloudflare/Sentry) | Phase 7 hosted acceptance + Phase 5 relevant gates + vendor legal/security and separate authorization | `docs/phase-8-plan.md`: plan-only; current artifacts must be verified from source, not inferred from proposal | Hold; do not build, provision, or deploy until prerequisites and per-service authorization are satisfied |
| 8 | Phase 9 AI/agent + production integration | Phase 7 hosted acceptance + Phase 5 unblock + Phase 6 tested + Phase 8 authorized framework | `docs/phase-9-plan.md`: historical transition reconciled; depends on 5/6/7/8 | Hold; no broker or external-service activation from historical plan text |

## Dependency rules (from docs cross-reference)
- Phase 2 → Phase 3 → Phase 4 → Phase 5 remains the product dependency chain. The strategy hash work does not certify all of Phase 3; paper order simulation does not certify Phase 4 reconciliation.
- Phase 5 safety hardening may land before live eligibility, but broker execution remains disabled until durable intent/recovery, independent broker-origin fill ingestion, accepted reconciliation evidence (≥1,000 settled real fills, <0.1%), identity/risk controls, legal/security review and explicit written authorization are all established.
- Phase 6 retained context may be developed independently of broker execution; OpenBB history is retired. Phase 7 hosting/security conditions are deployment-specific and must not be inferred completed from starter artifacts.
- Phase 8 requires Phase 7 complete + Phase 5 prerequisites + vendor legal/security (`phase-8-plan.md` lines 10-14).
- Phase 9 requires Phase 7 + Phase 5 unblock + Phase 6 tested + Phase 8 framework (`phase-9-plan.md` prerequisites); historical transition text is not current authorization.
- `docs/phase-0-plan.md` excluded by `.gitignore`; not cited as source; use `phase-0-safety.md` / `catalogue.md` / `increment4.md` instead.

## Ticks by file (for editors)
- `docs/phase-1-plan.md`: 1.1/1.2/1.3 ticked; 1.4/1.5 open.
- `docs/phase-2-plan.md`: status qualified as partially verified; existing adapters acknowledged, acceptance gaps retained.
- `docs/phase-3-plan.md`: status qualified as partially verified; hash/version improvements separated from full studio/backtesting completion.
- `docs/phase-4-plan.md`: expanded from a 3-line stub to state the real-evidence gate and current not-verified status.
- `docs/phase-5-plan.md`: updated for implemented guards/routes and remaining gated lifecycle/evidence work.
- `docs/phase-5-prerequisites.md`: corrected stale missing-adapter inventory and clarified evidence/dependency gates.
- `docs/phase-6-plan.md`: historical-data retirement and retained-context scope recorded; production license gate remains.
- `docs/phase-7/8/9-plan.md`: stale readiness descriptions reconciled; historical authorizations clarified as not current deployment/build approval.
- `docs/backups.md` / `legal.md` / `monitoring.md` / `security.md` / `terms.md`: not edited this pass (no task-checkmarks requested); read but not compared to index.
