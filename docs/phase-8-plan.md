---
#### **`docs/phase-8-plan.md`**
```markdown
# Phase 8 — External Service Integration Layer (plan-only, 2026-09-20)

> Status: **Plan document only — NO build authorization.** Phase 7 (SEO/discovery/404/cookie/terms/analytics/CTA + sitemap/robots/llms) must complete; Phase 5 live-broker prerequisites remain BLOCKED and gate Stripe live payments / auth-to-broker linkage. All 7 services planned (Supabase, Stripe, Vercel, Resend, Auth0, Cloudflare, Sentry); starter env/config templates proposed; no deploy, no secrets.
>
> Source: user clarification — Phase 8 plan-only, all 7 services, wait for Phase 7, build later.

## Prerequisites (ALL must complete before ANY build of this layer)

- [ ] Phase 7 complete — sitemap + robots + llms + canonical/noindex + meta/alt/schema + links + broken links + HTTPS + slugs + backlink + analytics/CTA + cookie/terms
- [ ] Phase 5 prerequisites met — paper reconciliation ≥1000 <0.1%, pen test / dependency audit / secrets, legal/compliance (FINRA/SEC if US), written authorization, `GATEWAY_EXECUTION_MODE=paper`, `ENABLE_LIVE_ALPACA` false, `alpaca_live.py` draft → production adapter
- [ ] Security / legal / compliance review for all 7 vendors; secrets plan (Vault/KMS/env-only); feature flags (`ENABLE_*`) all default false; `config.py` confirmed
- [ ] Dependency audit: `requirements.txt` / `docker-compose.yml` updated (proposed pins for `supabase`, `stripe`, `resend`, `authlib`, `sentry-sdk`); NO live keys
- [ ] Frontend build pipeline verified (`frontend/src/`); Vercel preview-deploy workflow proposed; env injection (`VITE_*`) planned
- [ ] Existing `auth.py` reviewed; Auth0 OIDC point mapped; session strategy chosen; fallback preserved
- [ ] DB migration strategy decided (`quant_app.db` → Supabase PG); rollback; `ENABLE_SUPABASE` false until verified
- [ ] Domain / HTTPS from Phase 7; Cloudflare tunnel (dev only) documented; WAF rules drafted

## Status / Authority

- Phase: 8 | Mode: **Plan only — NO build** | Released: 2026-09-20 | Build target: not committed
- Live-payment / live-broker gates: **Intentionally unavailable** (Stripe blocked by Phase 5; all `ENABLE_*` false)
- Prior phases preserved: Phase 5 (blocked), Phase 6 (OpenBB proposed), Phase 7 (build-transition completed)

## Slices (7 services — 3 groups: A Foundation, B Payments+Deploy, C Auth+Integration)

### 8.1: Supabase — PostgreSQL DB + Auth integration
- `quant-app-v1/backend/app/providers/supabase_client.py` (NEW); `services/db_migration.py`; `config.py`; `requirements.txt`; `docker-compose.yml` (optional service)
- Integration: `auth.py` (JWT/RLS or fallback); `provider_registry.py`; `market_data.py`; DB schema `orders/fills/positions/users/profiles`
- Flag: `ENABLE_SUPABASE=false`; env `SUPABASE_URL`, `*_ANON_KEY`, `*_SERVICE_ROLE_KEY`

### 8.2: Resend + Sentry (parallel within Group A)
- `services/email_service.py` (extend); `services/sentry_service.py`; `config.py`; frontend `sentryInit.ts`; `requirements.txt`
- Integration: `auth.py` (email); `main.py` (Sentry init); PII `before_send` filter; Phase 5 audit/replay linkage (planned, not implemented)
- Flags: `ENABLE_RESEND=false`; `ENABLE_SENTRY=false`; env `RESEND_API_KEY`, `SENTRY_DSN`

### 8.3: Stripe — Payments / subscriptions (GATED — Phase 5 required)
- `api/v1/stripe/webhook.py`; `services/stripe_service.py`; `config.py`; `requirements.txt`
- Integration: `auth.py` (tier); `live_gates.py` (Phase 5 gate — subscription-active check planned); `frontend/` tier picker (planned)
- Flag: `ENABLE_STRIPE=false` (hard gate); env `STRIPE_*`; skeleton webhook only; `FeatureDisabled` when false
- Unavailable until Phase 5 gates clear + explicit authorization

### 8.4: Vercel — Frontend deploy + Cloudflare — CDN / DNS / WAF / HTTPS
- `vercel.json`; `.vercel/env/` (planned, never commit); frontend build env (`VITE_*`); Cloudflare zone / DNS CNAME / WAF / HTTPS plan
- Integration: `config.py` (CORS origins include Vercel previews); Phase 7 HTTPS connects; `cloudflared` tunnel (dev only)
- Flags: `ENABLE_VERCEL_DEPLOY=false`; `ENABLE_CLOUDFLARE=false`

### 8.5: Auth0 — SSO / OIDC (replaces / augments auth.py)
- `auth.py` (extend, not edited now); `services/session_service.py`; `frontend/auth/auth0Init.ts`; `config.py`; `requirements.txt`
- Integration: `auth.py` (primary/secondary); `supabase_client.py` (8.1 linkage planned); `email_service.py` (reset); `stripe_service.py` (user-sub metadata)
- Flag: `ENABLE_AUTH0=false`; env `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`

### 8.6: Cross-service integration + feature flags + env/template starters
- `services/integration_flags.py`; `main.py` (conditional init order); `.env.example` (starter); `requirements.txt`; `docker-compose.yml`
- All 7 flags + existing preserved: `ENABLE_SUPABASE`, `ENABLE_STRIPE`, `ENABLE_VERCEL_DEPLOY`, `ENABLE_RESEND`, `ENABLE_AUTH0`, `ENABLE_CLOUDFLARE`, `ENABLE_SENTRY` — all `false`; `GATEWAY_EXECUTION_MODE=paper`; `ENABLE_LIVE_ALPACA=false`; `ENABLE_OPENBB_DATA=false`

### 8.7: Acceptance + transition + intentionally unavailable
- All `false` default; server starts; no secrets committed; `.env.example` only; feature flags documented
- Build transition: Phase 7 done + Phase 5 clear + user per-slice authorization → 8.1→8.2→8.3(gated)→8.4→8.5→8.6→8.7
- Rollback per service: flag false + restart + rollback script / previous deploy / disable proxy
- Security: `grep` for `sk_live` / `sk_test` / `supabase.*key` / `auth0.*secret` / `sentry.*dsn` must pass; Vault/KMS/env-only

## File Paths (new + modified — proposed, not created)

**New (build when authorized)**
- `quant-app-v1/backend/app/providers/supabase_client.py`
- `quant-app-v1/backend/app/services/db_migration.py`
- `quant-app-v1/backend/app/services/email_service.py` (extend)
- `quant-app-v1/backend/app/services/sentry_service.py`
- `quant-app-v1/backend/app/services/stripe_service.py`
- `quant-app-v1/backend/app/services/session_service.py`
- `quant-app-v1/backend/app/services/integration_flags.py`
- `quant-app-v1/backend/app/api/v1/stripe/webhook.py`
- `quant-app-v1/backend/app/config.py` (extend — flags + env)
- `quant-app-v1/backend/app/main.py` (conditional init — planned)
- `quant-app-v1/frontend/src/utils/sentryInit.ts`
- `quant-app-v1/frontend/src/auth/auth0Init.ts`
- `quant-app-v1/vercel.json`
- `quant-app-v1/.env.example` (starter; never `.env`)
- `docs/phase-8-plan.md` (this document)

**Modified (planned)**
- `quant-app-v1/backend/app/auth.py` (Auth0 extend — proposed, not edited in plan)
- `quant-app-v1/backend/app/providers/provider_registry.py` (supabase entry — planned)
- `quant-app-v1/backend/app/requirements.txt` (additions proposed; none installed yet)
- `quant-app-v1/docker-compose.yml` (optional services documented)
- `quant-app-v1/frontend/src/` (build-time env; `ENABLE_*` consumption)

## Dependency / License Notes
- All 7 services external; no license conflict with AGPLv3 OpenBB (Phase 6) except Auth0 terms (enterprise) and Stripe terms (payment processing); Supabase (Apache 2 / proprietary DB); Vercel / Cloudflare / Resend / Sentry standard SaaS terms
- `openbb` (Phase 6) preserved; `alpaca` (Phase 5) preserved; no removal of existing dependencies

## Acceptance Criteria (proposed for future build verification)
- All `ENABLE_*` false; server starts; no crashes; `.env` absent; `.env.example` present; no secrets in repo
- `.env.example` defines all env keys (no values); `grep` for live-key patterns passes
- Feature-flag framework (`integration_flags.py`) exists; each service has `is_enabled()`
- Integration points mapped: `auth.py`, `config.py`, `providers/`, `services/`, `api/`, `requirements.txt`, `docker-compose.yml`, `frontend/src/`
- Phase 5 gate documented for Stripe; `stripe_service.py` returns `FeatureDisabled`; webhook skeleton validates `Stripe-Signature` (test only)
- Phase 7 prerequisite confirmed; Phase 6 preserved; Phase 5 preserved (blocked)

## Intentionally Unavailable
- Stripe live payments / webshop / subscription — Phase 5 gates required (`alpaca_live.py` draft; no paper reconciliation; no pen test; no legal; `ENABLE_LIVE_ALPACA` false); webhook skeleton only
- Auth0 production SSO — `ENABLE_AUTH0` false; existing auth unchanged
- Supabase production DB — `ENABLE_SUPABASE` false; `quant_app.db` preserved; dry-run migration only
- Resend live email — `ENABLE_RESEND` false; console/log only
- Sentry live ingestion — `ENABLE_SENTRY` false; stderr only; PII filter unverified
- Vercel production deploy — `ENABLE_VERCEL_DEPLOY` false; preview workflow documented
- Cloudflare production CDN/WAF/HTTPS — `ENABLE_CLOUDFLARE` false; Phase 7 HTTPS connects first; tunnel (dev) only
- Phase 5 audit/replay → Sentry `trace_id` linkage — unavailable until Phase 5 build

## Build / Transition Notes
- Mode: plan → build when Phase 7 complete + Phase 5 complete + user per-slice authorization
- Sequence: 8.1 → 8.2 (parallel option) → 8.3 (gated) → 8.4 → 8.5 → 8.6 → 8.7
- Rollback per service defined; secrets never committed; `grep` check required pre-commit
- This document is source of truth; actual `supabase_client.py` / `stripe_service.py` / etc. written only when authorized
- Phase 6 (OpenBB) and Phase 7 (SEO) references preserved; no regression
