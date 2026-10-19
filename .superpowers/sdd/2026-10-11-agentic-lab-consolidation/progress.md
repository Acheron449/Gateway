# SDD ledger — plan: docs/superpowers/plans/2026-10-11-agentic-lab-consolidation.md

Ruling: Execute in the current shared workspace rather than create a worktree — approved Native continuation targets existing changes in the user's workspace; making a second tree would strand the interrupted edits — cost if wrong: workspace isolation is reduced.

Pre-flight: Shared API/service contracts — Task 2 produces bounded `bar_returns` and authenticated Monte Carlo API; Task 3 consumes/persists those returns with owner filters, and Task 4 consumes Monte Carlo and job APIs. Existing code currently implements both sides; verify exact schemas during tests.

Ruling: The plan references unavailable `superpowers` scripts and test-driven-development skill resources — use the repository plan/spec, add/execute focused tests directly, and maintain this ledger manually — cost if wrong: task receipts do not have the skill script's independent automation.

## Completion receipts (2026-10-12)

- Consolidation implementation is present: Tauric dedicated routes/service/UI/Docker install removed; Agentic Lab has the five requested tabs, one run-history/backtester surface, pair launcher in Cointegration Pairs, seeded Monte Carlo comparison, and bounded owner-scoped iterative research/cancellation.
- Focused backend verification: `JWT_SECRET_KEY=test-secret PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_agentic_lab.py tests/test_job_store.py tests/test_deploy_hardening.py tests/test_auth_preferences.py tests/test_journal_and_vault.py` — **61 passed**.
- Frontend verification: `npm run build` — **passed** (TypeScript and Vite; existing large-chunk advisory).
- Full backend `pytest -q` was attempted; **65 collection errors**, including SciPy `_propack` binary load failure, Pydantic strategy test `Any` NameError, and vendored/optional dependency collection errors. A retry excluding pairs still stopped at the strategy regression test. Pair-specific execution tests therefore remain unverified in this environment.
- Browser smoke with local frontend and backend: five tabs render, pairs launcher is located in Pairs, Monte Carlo is present in Backtests, and `/app/backtests` redirects correctly. Health/OpenAPI/provider/run/research/agent endpoints answered; removed `/agents/trading-agents` is 404. External quote/calendar calls included provider 503s. No real LLM request was submitted.
- Docker build was not run because Docker CLI is unavailable. Final source/docs diff check must be run after this ledger update.

## Deferred user-request items

Model auto-discovery with free-only filtering, yfinance calendar integration, Financial Modeling Prep removal, and scanner/search-command consolidation were explicitly kept outside this consolidation increment. The current code inspection confirmed an authenticated `/llm/providers/{provider_id}/models` route exists, the calendar auto-chain still contains FinancialModelingPrep and lacks Yahoo Finance, and Scanner is still a standalone view plus a separate command-palette entry. They need their own reviewed designs/plans before implementation.
