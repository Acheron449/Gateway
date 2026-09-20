---
#### **`docs/phase-9-plan.md`**
```markdown
# Phase 9 — AI / Agent Integration + Phase 5 Unblock + Production Hardening (build transition, 2026-09-20)

> Status: Build-mode active (user: AI/agent direction + unblock Phase 5 + plan + build 7/8 starters). Plan mode lifted for artifacts only.
> Prerequisites: Phase 7 (215 lines, build-transition: sitemap/robots/llms/canonical/alt/meta/links/HTTPS/slugs/backlinks/analytics/CTA/cookie/terms/404) must complete; Phase 5 (BLOCKED — alpaca_live.py draft, prerequisites not met) must unblock for live-broker + Stripe + audit-replay linkage; Phase 6 (OpenBB proposed) preserved; Phase 8 (all 7 services planned, ENABLE_*=false) preserved.

## Direction (user-confirmed)
- Phase 9 = AI / agent integration (OpenBB + gateway → AI copilot / MCP / agent interface)
- Parallel: Phase 5 unblock (live broker adapter from draft to production; prerequisites: reconciliation ≥1000, pen test, legal, authorization)
- Build 7 starters (HTTPS meta/alt/link fixes, sitemap deployment, analytics snippet install)
- Build 8 starters (.env.example, vercel.json, integration_flags skeleton)

## Prerequisites (all must clear)
- [ ] Phase 7 complete (currently build-transition; 215 lines; artifacts written: sitemap, robots, llms, 404, cookie, terms, analytics, CTA — need HTTPS redirect + meta injection + alt fixes + broken-link scan + Core Web Vitals)
- [ ] Phase 5 prerequisites: paper reconciliation ≥1000 trades <0.1%; security review; legal/compliance; written user authorization; `ENABLE_LIVE_ALPACA` false → true with gates; `alpaca_live.py` draft → full adapter
- [ ] Phase 6 OpenBB data feed tested (package + server; `ENABLE_OPENBB_DATA` false → test true)
- [ ] Phase 8 feature flags framework (`ENABLE_*` all false; `.env.example` starter; `integration_flags.py` planned)

## Slices

### 9.1: Phase 5 Unblock — Live Broker Adapter (Week 1–4; HARD GATE)
- `quant-app-v1/backend/app/providers/alpaca_provider.py` (reference for interface; `alpaca_live.py` currently 3-line draft)
- Convert `alpaca_live.py` from draft to production adapter: live endpoints, idempotency (UUID v7), partial fills, reconciliation (every 5 min), kill switch, account sync
- Prerequisites must be PROVEN before `ENABLE_LIVE_ALPACA=true`: 1000+ paper trades <0.1% discrepancy; pen test pass; legal sign-off; user written authorization
- Only after unblock: Stripe (8.3) can consider `ENABLE_STRIPE=true`; Auth0 (8.5) can link to live-account tier

### 9.2: AI / Agent — OpenBB → Agent Interface (Week 2–5; independent of Phase 5)
- `quant-app-v1/backend/app/ai/agent_interface.py` (NEW): wrap `openbb` (Phase 6) + gateway data → agent-readable format; MCP server skeleton (`openbb-mcp`) referencing `https://github.com/OpenBB-finance/OpenBB`
- Integration: OpenBB equity/crypto/fixed-income → agent prompts → gateway quant pipeline (backtester/risk) → recommendations; feature flag `ENABLE_AI_AGENT` (default false)
- File paths: `backend/app/ai/`, `backend/app/services/agent_service.py`; frontend `src/components/AgentPanel.tsx` (planned)

### 9.3: Production Hardening — Monitor / Security / Close Phase 7 (Week 3–6)
- Build Phase 7 starters: HTTPS redirect (nginx/config), meta tags (per doc), alt text (images), schema JSON-LD, internal links, broken-link fix, Core Web Vitals (LCP/INP/CLS), backlink verification
- Build Phase 8 starters: `.env.example`, `vercel.json`, `integration_flags.py` skeleton; install `supabase`/`stripe`/`resend`/`authlib`/`sentry-sdk` only in test env, never prod without auth
- Monitoring: Prometheus/Grafana dashboard (Phase 5.4 style); Sentry `ENABLE_SENTRY` true in staging; Cloudflare WAF rules

### 9.4: Cross-Integration — Phase 5 + 6 + 7 + 8 + 9 (Week 6–10)
- Live broker (Phase 5, now unblocked) feeds audit log (Phase 5.3) → replay (Phase 5.3) → agent (9.2) → monitoring (9.3) → Stripe tier (8.3 gated, now eligible if subscription-linked) → Auth0 SSO (8.5) → Supabase DB (8.1) → Vercel deploy (8.4)
- Feature flags control each layer; `main.py` init order: config → Sentry (9.3) → DB (8.1, false) → Auth (existing/8.5, false) → OpenBB (6) → Agent (9.2, false) → Stripe (8.3, false until Phase 5) → Resend (8.2, false)

## Acceptance Criteria (proposed)
- `alpaca_live.py` production adapter complete; prerequisites verified; `ENABLE_LIVE_ALPACA=true` authorized
- `ENABLE_AI_AGENT` false by default; agent interface wraps OpenBB; MCP reference added; no live agent without user authorization
- Phase 7 artifacts deployed: sitemap live, robots live, HTTPS redirect, meta tags, schema, links fixed, Core Web Vitals measured
- Phase 8 starters present: `.env.example`, `vercel.json`, `integration_flags.py`; `ENABLE_*` all false; no secrets
- Monitoring dashboard shows Phase 5 audit + Phase 9 agent metrics; Sentry active in staging only

## Intentionally Unavailable
- Full Phase 5 live trading until prerequisites verified; Stripe live until Phase 5 + subscription gate; Auth0 production SSO until build authorized; Supabase production DB until migration verified; Cloudflare WAF until Phase 7 HTTPS complete; AI agent live recommendations until human-in-loop authorization
ENDOFFILE
echo "Phase 9 doc: $(wc -l < docs/phase-9-plan.md) lines"