# Gateway — Completion Status

> Last updated: 2026-10-04. Companion to the phase plans (`phase-N-plan.md`):
> those documents describe *intent and gates*; this file records what has
> actually been **built and verified** versus what remains.

## Completed (built and verified)

### Core platform (Phases 0–4)
- Provider layer with encrypted API-key store, registry, and canonical
  `MarketDataProvider` contract (`app/providers/`); Yahoo Finance via
  `yfinance` is the keyless default.
- Market data: `/history/{sym}` with a selectable provider chain
  (Yahoo → TradingView → AllTick → Alpaca → OpenBB), candle resampling,
  provenance on every row; batch `/quotes` for the ticker strip (45s merge
  cache).
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

### Agentic Trading Lab — *completed*
- LLM/agent dashboard, backtest jobs with model decisions, baselines,
  metrics in plain language, runs persistence (≤50), research documents
  (typed/uploaded/model-generated), trading log, performance cards.
- **RiskGuard port** from `kweinmeister/agentic-trading`: max-position cap,
  drawdown circuit breaker, short filter; every decision annotated
  approved/blocked/halted; `Risk guard` stat row, log column and badges.
- **Reference results chart**: price + SMA 10/30 with open/close/risk
  markers (`build_chart` → `RunChart`).
- **TradingAgents (Tauric Research)** integration: analyst selection,
  progress via job polling, report sections; one run at a time.

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

### Verification status (2026-10-04)
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
- **Docker build not run here** (no docker CLI): run `docker compose build`
  locally — it installs TradingAgents from git and picks up the new
  `ccxt` requirement.
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
