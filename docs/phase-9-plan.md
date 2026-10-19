---
#### **`docs/phase-9-plan.md`**
```markdown
# Phase 9 — AI / Agent Integration + Phase 5 Unblock + Production Hardening (build transition, 2026-09-20)

> Status: **Historical plan; no current build/deployment authorization.** Phase 7 starter artifacts do not establish hosted acceptance; Phase 5 remains blocked (broker order placement fails closed, `/live` routes unmounted, real reconciliation evidence absent); Phase 6 retains quote/news/calendar context only and retires historical OHLCV; Phase 8 remains plan-only. Historical transition wording below is not current permission to enable live services.

## Direction (user-confirmed)
- Phase 9 = AI / agent integration (OpenBB + gateway → AI copilot / MCP / agent interface)
- Phase 5 remains a hard gate; do not implement or enable broker execution from this historical direction without a separately reviewed authorization and real evidence.
- Historical Phase 7/8 starter implementation notes only; any hosting, deployment, vendor installation, or feature activation requires separate current authorization.

## Prerequisites (all must clear)
- [ ] Phase 7 production acceptance: starter files exist, but hosted HTTPS, canonical/meta, alt/schema, crawl/link, slug, performance, analytics/cookie and backlink checks remain unverified.
- [ ] Phase 5 prerequisites: independently verified ≥1,000 settled real broker-origin fills with <0.1% discrepancy; accepted ingestion/comparator; durable order-intent recovery; security/legal/account ownership; explicit written authorization. Current adapters intentionally fail closed and routes remain unmounted.
- [ ] Phase 6 retained quote/news/calendar context acceptance tested; OpenBB historical data is retired and AGPLv3 review remains a production prerequisite.
- [ ] Phase 8 remains plan-only with no current build authorization; verify current repository for starter files and keep external integrations disabled until explicit approval.

## Slices

### 9.1: Phase 5 Unblock — Live Broker Adapter (Week 1–4; HARD GATE)
- Historical adapter references must be checked against current paths: `alpaca_provider.py` is the market-data provider; guarded execution adapters are in `app/services/`.
- Any broker adapter work is future-gated and must first have a reviewed durable intent/recovery and broker-origin fill-ingestion design. This plan does not authorize live endpoints or order placement.
- Phase 5 must remain blocked until independently verified ≥1,000 settled real broker-origin fills with <0.1% discrepancy, accepted ingestion/comparator, durable intent/recovery, identity/risk/security/legal controls, and explicit written authorization.
- Any later Stripe/Auth0/broker account linkage requires its own service/security/legal design and explicit authorization; it is not enabled by satisfying a roadmap prerequisite alone.

### 9.2: AI / Agent — OpenBB → Agent Interface (Week 2–5; independent of Phase 5)
- `quant-app-v1/backend/app/ai/agent_interface.py` (NEW): wrap `openbb` (Phase 6) + gateway data → agent-readable format; MCP server skeleton (`openbb-mcp`) referencing `https://github.com/OpenBB-finance/OpenBB`
- Integration: OpenBB equity/crypto/fixed-income → agent prompts → gateway quant pipeline (backtester/risk) → recommendations; feature flag `ENABLE_AI_AGENT` (default false)
- File paths: `backend/app/ai/`, `backend/app/services/agent_service.py`; frontend `src/components/AgentPanel.tsx` (planned)

### 9.3: Production Hardening — Monitor / Security / Close Phase 7 (Week 3–6)
- Close Phase 7 hosted acceptance only when hosting/domain exists and the user authorizes those checks; starter files alone are not sufficient.
- Phase 8 remains plan-only; do not install vendors, create accounts, provision services, or deploy from this historical phase description.
- Monitoring: Prometheus/Grafana dashboard (Phase 5.4 style); Sentry `ENABLE_SENTRY` true in staging; Cloudflare WAF rules

### 9.4: Cross-Integration — future gated sequence (Week 6–10)
- Only after the independently reviewed Phase 5 gates and explicit authorization may a future integration design connect broker audit/replay to agent, monitoring, payment, auth, storage, or deploy services. This plan does not authorize that sequence.
- Future integration initialization order must be designed and verified per authorized service; this historical sketch is not an implementation contract.

## Acceptance Criteria (historical proposal; not current authorization)
- Broker execution remains disabled unless and until every independently reviewed Phase 5 gate is met and a separate written authorization explicitly permits its scope.
- `ENABLE_AI_AGENT` false by default; agent interface wraps OpenBB; MCP reference added; no live agent without user authorization
- Phase 7 hosted acceptance demonstrated on an authorized host; current status remains unverified.
- Any Phase 8 artifacts and service flags verified from current source and independently authorized before use; no secrets committed.
- Monitoring/audit/agent integration explicitly tested under a separately reviewed design; not delivered by this plan increment.

## Intentionally Unavailable
- Broker calls, broker orders and live trading: current adapters fail closed and `/live` is unmounted; no live authorization.
- Stripe live until independently verified Phase 5 gates and separate explicit authorization; Auth0 production SSO until separately authorized; Supabase production DB until migration verified; Cloudflare WAF until Phase 7 HTTPS complete; AI agent live recommendations until human-in-loop authorization.
- Historical OpenBB OHLCV support (retired); use existing historical-market-data providers.

> Reconciled 2026-10-18: no real reconciliation evidence, broker order-intent/recovery lifecycle, or broker-fill ingestion was implemented in the paper-safety increment. No broker calls, orders, deploys, commits, or pushes are authorized by this document's historical transition text.
