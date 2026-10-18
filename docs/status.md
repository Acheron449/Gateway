# Gateway — Completion Status

> Last updated: 2026-10-18. Companion to the phase plans (`phase-N-plan.md`):
> those documents describe *intent and gates*; this file records what has
> actually been **built and verified** versus what remains.

## Completed (built and verified)

### Core platform (Phases 0–4)
- Provider layer with encrypted API-key store, registry, and canonical
  `MarketDataProvider` contract (`app/providers/`); Yahoo Finance via
  `yfinance` is the keyless default.
- Market data: `/history/{sym}` with selectable historical sources (Yahoo
  Finance, TradingView, AllTick, Alpaca, Finnhub, CCXT, and LSE), Yahoo as
  the default, and CCXT as a crypto backup; candle resampling and provenance
  on every row. OpenBB is not a historical source. Batch `/quotes` powers
  the ticker strip (45s merge cache).
- News/calendar/quote endpoints with **multi-source fallback chains**
  (`provider=auto`), provenance, and persistence (`news_service`,
  `calendar_service`).
- Auth (JWT), watchlists, layouts, preferences, symbol search, analysis,
  risk dashboard, divergence scorecards, strategy studio, paper trading
  (portfolio/orders/fills/kill-switch), journal.
- Frontend shell: sidebar views, top-bar ticker marquee, right inspector,
  charts, scanner, markets, calendar.

### AI Chat (harness) — *completed*
- `/llm/*` provider CRUD (11 catalogued providers: OpenAI-compatible group —
  OpenRouter, Ollama local/cloud, OpenCode Zen, Cloudflare AI Gateway, Groq,
  Kilo, custom — plus OpenAI/Anthropic/Gemini), Fernet-encrypted keys, model
  listing, SSE chat streaming, context feeder (`/llm/context`).
- Chat UI: sessions sidebar with past-chat restore/delete, composer with
  model picker and context panel, streaming with abort.
- **2026-10-04:** decorative "gateway" watermark removed from the empty-state
  hero; the two guidance lines are preserved.

### Agentic Trading Lab — *core features completed; consolidation verified 2026-10-12*
- LLM/agent dashboard, backtest jobs with model decisions, baselines,
  metrics in plain language, runs persistence (≤50), research documents
  (typed/uploaded/model-generated), and owner-filtered trading log.
- **Unified Agentic Lab:** the five tabs are LLMs, Research, Trading Log,
  Backtests, and Cointegration Pairs. Standalone Backtester navigation and
  duplicate pair-launch locations are removed; legacy `/app/backtests`
  links redirect to the Backtests tab. Backtests owns run history/detail,
  including pair folds/fills and multi-strategy Monte Carlo comparison.
- **Monte Carlo:** seeded historical-return bootstrap compares up to eight
  eligible single-strategy runs with deterministic strategy colors and an
  explicit non-forecast/overfitting disclaimer. Pair and legacy runs without
  full-resolution return data are excluded, not approximated.
- **Iterative research:** authenticated, owner-scoped, cooperative-cancel
  jobs use bounded model-call and iteration caps. Public historical prices,
  the caller's research, and outputs from that job are the only research
  context; the loop cannot read portfolio/account details or place orders.
- **Tauric Research TradingAgents** dedicated API/service/UI and remote
  Docker installation removed. Shared LLM providers and Agentic Lab remain.
- **RiskGuard port** from `kweinmeister/agentic-trading`: max-position cap,
  drawdown circuit breaker, short filter; every decision annotated
  approved/blocked/halted; `Risk guard` stat row, log column and badges.
- **Reference results chart**: price + SMA 10/30 with open/close/risk
  markers (`build_chart` → `RunChart`).

### Overview redesign — *completed (2026-10-04)*
- Reference-style dashboard (`OverviewDashboard.tsx`): market-overview
  ticker strip with sparklines, main chart with 1D–ALL range tabs, market
  movers (gainers/losers), news card with category tabs, SEC filings card
  (Watchlist/Recent/Insider/Transcripts), risk summary with derived
  checklist + concentration bars, watchlist table (Price/1D/YTD), sector
  heat map. Panels fetch existing endpoints only; rows/cards are capped to
  fit their panels.

### News sources — *completed (2026-10-04)*
- **yfinance as a news source**: `YahooFinanceProvider.news()` uses
  yfinance's `YfData` session against Yahoo's public search/news endpoint;
  items keep their publisher and carry a thumbnail (`NewsItem.thumbnail`,
  DB column added).
- `/news` default is now `provider=auto` walking **Finnhub → Yahoo Finance**
  (same semantics as the calendar chain); explicit providers stay strict.
  `/news/sources` lists availability for the UI picker.
- **Preview caps**: right inspector shows 4 stories + "View all news";
  Overview news card shows 4 + "View all".
- **Full-page scrollable news** (`NewsPage.tsx` overlay): 50 stories,
  category tabs, source picker (auto/chain members), keyboard close.

### Market-data backup: ccxt — *completed (2026-10-04)*
- `CCXTProvider` (keyless public exchange OHLCV/tickers; default exchange
  Kraken, `GATEWAY_CCXT_EXCHANGE` overrides) registered in the provider
  registry.
- `/history` accepts `provider=ccxt` (chart provider picker includes it),
  and **falls back to ccxt automatically when yfinance fails** on a
  crypto-shaped symbol before returning 502. Non-crypto requests degrade
  back to yfinance via the exchange's symbol rejection.
- `requirements.txt`: `ccxt>=4.0.0` added.

### SEC filings — *completed (2026-10-04)*
- `GET /filings?symbols=…` backed by `yfinance.Ticker.get_sec_filings()`
  (public SEC/EDGAR feed), 10-minute TTL cache, newest-first merge; degrades
  to an empty feed on yfinance pins that predate the API.

### Verification status (2026-10-12 consolidation)
- Focused backend suite: **61 passed** across Agentic Lab, job store, deploy
  hardening, auth preferences, and journal/vault.
- Frontend `npm run build` (TypeScript + Vite): passed; Vite emitted its
  existing >500 kB chunk-size advisory.
- Full backend `pytest -q` did **not** pass collection (65 collection errors).
  Failures include a local SciPy `_propack._spropack` loader error for pairs,
  Pydantic `NameError: Any` while collecting the strategy regression test,
  and missing/incompatible optional dependencies while pytest discovers vendored
  Kronos/TradingAgents tests. A retry excluding the pairs test still stopped
  on the strategy regression collection error. These are reported as blocked
  checks, not passing tests; the focused suite above ran independently.
- Browser smoke test with local frontend/backend: all five Agentic Lab tabs
  render; Backtests displays run history and Monte Carlo controls/disclaimer;
  Cointegration Pairs contains the launcher; `/app/backtests` redirects to
  `/app/agentic-lab?tab=backtests`. `/health`, `/openapi.json`, provider,
  research, agent and run-list APIs returned 200; Monte Carlo/research routes
  are registered and the removed `/agents/trading-agents` route returns 404.
  Some external quote/calendar provider requests returned 503 during the
  smoke test; no real provider-backed LLM job was submitted.
- Docker build not run (Docker CLI unavailable).

### Previous verification status (2026-10-04)
- `tsc --noEmit`: 0 errors.
- Backend `py_compile`: clean; app imports and serves all new routes.
- `pytest`: 11 new tests in `tests/test_data_sources.py` (news chain,
  yfinance news mapping, ccxt symbol/provider behavior, history ccxt
  backup, filings) — **all passing**; full suite: 67 passing + the 2
  pre-existing failures documented on clean HEAD
  (`test_scraped_news_endpoint_is_explicitly_unavailable`,
  `test_empty_configured_results`) — not weakened.
- Playwright suites (`verify_agentic`, `verify_final`, `verify_risk`):
  ALL CHECKS PASSED with exit status preserved.
- Live smoke tests: Yahoo news (thumbnails + publishers), auto chain
  (Finnhub answered), `/filings` (real EDGAR rows), `provider=ccxt` history
  (`source: ccxt`), non-crypto fallback (`source: yfinance`).

## Remaining / not done

### This iteration
- **Model discovery/free-only filtering, yfinance calendar source, Financial Modeling Prep provider removal, and scanner-to-command-bar migration** remain unimplemented follow-up work; these systems were inspected but not changed in the consolidation increment.
- **Docker build not run here** (no docker CLI): run `docker compose build`
  locally to verify the backend image and current pinned dependencies.
- **Real LLM API keys untested**: model behavior verified only against the
  local fake OpenAI-compatible server (`127.0.0.1:9099`); wire a real key
  for a live smoke test.
- **Filings "Transcripts" tab** has no data source (SEC forms feed only) —
  shows an honest empty state; earnings-transcript source would need a new
  provider.
- **Market movers** has gainers/losers only — "Most Active" needs volume,
  which `/quotes` does not return yet.
- **Risk card** renders the risk module's demo dataset (`/risk/metrics`
  mock generator); linking it to the real risk engine/paper portfolio
  equity is still open.
- **Heat map** covers the liquid basket with static sector groups — not a
  full market/sector-membership map.
- **Watchlist YTD** issues one `/history` call per row (no client cache) —
  a batching endpoint or memoization would cut first-load chatter.
- `NewsFeed.tsx` is superseded by `OverviewDashboard`/`NewsPage` and no
  longer referenced — candidate for removal.
- E2E suites live in `/tmp` — not committed to the repo or CI; the
  provider-card check in `verify_agentic.js` has a load-timing flake
  (passes on rerun).
- `yfinance.Ticker.news` returns empty in this environment; the provider
  therefore uses the `YfData` search endpoint. If yfinance fixes
  `Ticker.news`, the provider can switch back.

### Project-level gates (see phase plans; intentionally untouched)
- **Phase 5** live broker: gated on reconciliation ≥1000 trades <0.1%, pen
  test, legal sign-off, written authorization; `ENABLE_LIVE_ALPACA=false`.
- **Phase 8** external services (Supabase/Stripe/Vercel/Resend/Auth0/
  Cloudflare/Sentry): plan-only, all `ENABLE_*` false.
- **Phase 9** AI agent interface / MCP: planned, `ENABLE_AI_AGENT` false.
