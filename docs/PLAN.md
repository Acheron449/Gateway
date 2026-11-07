# Gateway launch plan — P6 close-out to P7

**Status:** 2026-11-07. P6 code work is complete; nothing is committed. This plan
turns the staged changes into a verified deployment and records what must be
proven on a real stack before P6 can be signed off.

## Where the work stands

- Backend suite: **481 passed, 0 failed**. The full Playwright suite is **13
  passing**. `pip-audit`, `bandit -r app -lll` and `npm audit --omit=dev
  --audit-level=high` are clean and gated in CI.
- NFR-20..NFR-30 all pass, so the Phase D audit is complete. NFR-29's
  `notice_acceptances` table, RLS policy and RPCs are in `supabase/schema.sql`;
  applying that schema to the hosted project is part of deployment. No
  unblocked Phase D item remains.
- SRS NFR-6..NFR-19: 12 pass, 0 partial, 0 fail, 2 pass with caveat
  (NFR-14 secret history, NFR-15 live-provider SSE).
- P4's duplicate read surface is closed: `/app/backtests` hosts the LLM
  launcher and multi-run Monte Carlo comparison, and the in-lab Backtester
  panel/tab are removed. The P4 image-size and live-RLS gaps remain deployment
  checks.
- All P6 changes are staged in the working tree; there are no commits or pushes.
- Blockers outside the code: no LLM provider key is configured, the API host is
  still open decision O-1, and the old `.env.docker` secrets remain in history.

## Phase A — close P6

| # | Step | Evidence |
| --- | --- | --- |
| A1 | Review the staged diff and commit it (no push without owner approval). | `git diff --cached --stat`, clean tree |
| A2 | Rotate `JWT_SECRET_KEY` and the Postgres password; purge history if the repo was ever public. | new values in the host's secret store, SRS NFR-14 caveat closed |
| A3 | Choose the API container host (O-1), then deploy API, Pages and Supabase; set `VITE_API_BASE`, `VITE_SITE_URL`, `VITE_SUPABASE_*`, `GATEWAY_PROVIDER_KEY` and one provider key. | `/health` 200, sign-in works |
| A4 | Run the live chat smoke test and record the result. | `scripts/smoke_chat_stream.py … --max-chars 400` exits 0 |
| A5 | Update SRS NFR-15 to plain **Pass** once A4 passes. | SRS table and tally |

Commands for A4:

```bash
cd quant-app-v1/backend
PYTHONPATH=. ../../.venv/bin/python scripts/smoke_chat_stream.py \
  --provider openrouter --model <model> --max-chars 400
```

Exit 2 means the provider key is missing or unusable; do not mark NFR-15 closed.

## Phase B — verify the three environmental caveats

| # | Check | Passing result |
| --- | --- | --- |
| B1 | Production CSP and generated SEO files on the Pages origin. | `script-src 'self'` with no `unsafe-*`; `robots.txt`/`sitemap.xml` use the deployed host and no repo path |
| B2 | Foreign-origin mutation gate. | `POST $API/portfolio/orders` with `origin: https://evil.example` returns 403 |
| B3 | Supabase RLS isolation with two real accounts. | account B cannot read or mutate account A's rows; direct table reads return none |
| B4 | Deploy smoke test from `docs/deployment.md` §5. | health, SPA fallback, register/login, `/auth/me` all pass |

Record each result in the P6 evidence table; B1–B3 are the only checks that
cannot be reproduced locally.

## Phase C — P7 scope decision

The chat harness and Agentic Lab stay in the tree behind the private-data gate.
Before enabling them, decide whether to ship owner-scoped repositories or keep
the gate. If they ship, the live chat smoke test becomes a release gate for
every provider change. Do not start P7 work until Phase A and B are signed off.

## Phase D — finish the NFR-20..NFR-30 audit

NFR-20..NFR-30 are done: health/readiness, scrubbed request logs, opt-in
error aggregation, keyboard/contrast/1024 px accessibility, a persistent
simulated-results/not-advice notice, per-surface scope lines, per-user notice
acceptance and a claims audit. The Phase D audit is complete; there is no
unblocked Phase D item left. The next work is the owner decisions in Phase A/B.

| # | Item | Done when |
| --- | --- | --- |
| D1 | NFR-20 health payload | **Done 2026-11-07** — `/health` + `/health/ready` readiness (503 `degraded` on DB failure) and dependency-free `/health/live`; `tests/test_health.py` |
| D2 | NFR-22 error aggregation | **Done 2026-11-07** — `ErrorAggregator` is opt-in via `ERROR_AGGREGATION_ENABLED`, scrubs emails/tokens, and unhandled errors return a fixed 500; `tests/test_error_aggregation.py` |
| D3 | NFR-23..NFR-26 accessibility | **Done 2026-11-07** — keyboard palette/brand/cards/rows, signed non-colour cues, 52 px rails at ≤1024 px, 5.24:1 muted text and 2 px focus rings; `e2e/accessibility.spec.ts` (3 passing) |
| D4 | NFR-27..NFR-30 legal | **Done 2026-11-07** — persistent notice, existing per-surface scope lines, `/notices` per-user acceptance and live/profitability claim removal; `tests/test_notice_acceptance.py`, `e2e/legal.spec.ts` |

None needs credentials or a deployed stack.

## Risks

| Risk | Mitigation |
| --- | --- |
| Pages build rooted at the repository instead of the SPA | The root `package.json` builds the SPA into root `dist`; Python manifests now live under `quant-app-v1/backend`, so Pages does not run pip. Documented root and `quant-app-v1/frontend` configurations both build. |
| No provider key, so NFR-15 stays caveated | A3/A4; the runner already fails closed with exit 2 |
| O-1 host undecided, blocking all deployment checks | decide the container host first; Pages/Supabase work is independent |
| Secrets in git history | rotate before any deployment; purge if public |
| Large staged diff hides an unrelated change | review `git diff --cached` per area before committing |
