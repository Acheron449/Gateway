---
# Terms of Service / Terms — Gateway

## 1. Scope
This document governs use of the Gateway repository and any associated site / services (docs, phases, openbb integration references, analytics). It applies to all phases 0–7.

## 2. Open Source & Licenses
- Gateway source is provided as-is for research and development.
- References to <a href="https://github.com/OpenBB-finance/OpenBB">OpenBB</a> (https://github.com/OpenBB-finance/OpenBB) are subject to the <strong>AGPLv3</strong> license. Any derivative works incorporating OpenBB components must comply.
- Broker adapter references (Alpaca) may have separate terms; see Phase 5 prerequisites.

## 3. No Live Trading Guarantee
- Phase 5 (live broker / Alpaca live) prerequisites are <strong>not met</strong> (`alpaca_live.py` is draft; `ENABLE_LIVE_ALPACA` false). No account is eligible for live execution until all Phase 5 prerequisites complete (security review, legal/compliance, user authorization, reconciliation proven).
- This site does not offer live trading access today.

## 4. Data & Analytics
- We use analytics (Plausible / Google Analytics, configurable) only after cookie consent (`gateway_cookie_consent`). No tracking before consent.
- See cookie banner (`/public/cookie-banner.html`) and preferences settings.
- We do not sell data; no PII in URLs or analytics payloads.

## 5. Disclaimer
- OpenBB data is not guaranteed accurate; trading involves risk of loss.
- This is a research/development platform, not investment advice.
- Liability limited to extent permitted by law; see OpenBB disclaimer and Phase 5 legal review requirements.

## 6. Cookies
- Essential cookies (session, consent) always active.
- Analytics cookies only after consent.
- You may revoke consent via cookie banner or browser settings.

## 7. Contact / Updates
- Updates tracked in `docs/phase-7-plan.md`; terms updated when Phase 6/5 prerequisites change.
