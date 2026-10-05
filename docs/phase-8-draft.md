# Phase 8 — External Service Integration (Plan Draft — NO BUILD AUTHORIZED)

Status: Plan-only per docs/phase-8-plan.md. All 7 services listed; feature flags default false.

## Services (7, 3 groups)
- 8.1 Supabase (DB + Auth)
- 8.2 Resend + Sentry (parallel)
- 8.3 Stripe (GATED — Phase 5 prerequisites)
- 8.4 Vercel + Cloudflare (deploy + CDN/WAF/HTTPS)
- 8.5 Auth0 (SSO/OIDC)
- 8.6 Cross-service flags + env templates (.env.example only)
- 8.7 Acceptance + intentionally unavailable

## Prerequisites (NOT met — from phase-8-plan.md lines 10-19)
- Phase 7 complete
- Phase 5 prerequisites (reconciliation ≥1000 / pen test / legal / auth / paper mode)
- Security/legal review for all vendors
- Dependency audit; env templates; auth reviewed; DB migration decided; domain/HTTPS

## Feature flags (all false — per 8.6)
ENABLE_SUPABASE, ENABLE_RESEND, ENABLE_SENTRY, ENABLE_STRIPE, ENABLE_VERCEL_DEPLOY, ENABLE_AUTH0, ENABLE_CLOUDFLARE — default false. No secrets committed.

## Deliverables (planned, not built — matches plan 8.1-8.7)
- supabase_client.py skeleton
- db_migration.py stub
- email_service.py / sentry_service.py extensions (planned)
- stripe_service.py / webhook skeleton (FeatureDisabled when false)
- auth.py extension (planned, not edited)
- vercel.json / cloudflare zone plan (no deploy)
- integration_flags.py (all false)
- .env.example starter only

## Acceptance (plan-only, not testable)
- All flags false → server starts
- No live keys in repo
- Phase 5 prerequisites met before ANY live-payment / live-broker linkage

## Intentionally unavailable
- Stripe live payments (Phase 5 gate)
- Auth0 production SSO (needs Phase 7 HTTPS + review)
- Supabase write (DB migration unverified)
- Cloudflare tunnel / WAF (dev only documented)
- All external-service live endpoints
