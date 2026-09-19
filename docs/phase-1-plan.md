# Phase 1 — Linear-Inspired Terminal Shell & Discovery (4–8 weeks)

## User outcome

A trader opens Gateway and lands in a single focused workspace: left navigation with watchlists/saved screens, center canvas for the active symbol (chart, indicators, patterns, forecast), right inspector for decisions (price, events, signals, paper order preview, risk/provenance). They discover symbols via a first-class Scanner, save filter presets and watchlists, and recover their layout on return — never seeing raw JSON or prototype controls.

## Slices (in dependency order)

### Slice 1.1: Application Shell & Navigation (Week 1–2)
**Depends on:** Phase 0 complete (React/Vite app running, catalogue endpoints working)

**Deliverables**
- `quant-app-v1/frontend/src/components/layout/Shell.tsx` — persistent 3-zone layout (Left: Navigation, Center: Canvas, Right: Inspector); responsive: drawer on <1024px, fixed panels on desktop
- `quant-app-v1/frontend/src/components/layout/Navigation.tsx` — collapsible left rail with routes: Overview, Scanner, Markets, Calendar, Strategies, Backtests, Paper Trading, Journal
- `quant-app-v1/frontend/src/components/layout/CommandPalette.tsx` — ⌘K palette for navigation, symbol lookup, common actions (keyboard-first)
- Update `quant-app-v1/frontend/src/App.tsx` — routes wrapped in Shell; legacy `/dashboard`, `/main` deprecated/redirected
- CSS: near-black canvas, layered charcoal panels, hairline borders, one primary action colour per view (per ROADMAP.md visual principles)

**Acceptance criteria**
- Fresh load shows Shell with working Navigation
- ⌘K opens palette; keyboard navigates all primary routes
- Panels collapse cleanly at tablet/mobile widths
- No raw JSON or prototype controls visible

### Slice 1.2: Scanner as First-Class Product (Week 2–3)
**Depends on:** Slice 1.1 (Shell provides route mount point), Phase 0 `/catalogue/search` endpoint

**Deliverables**
- `quant-app-v1/frontend/src/components/features/ScannerV2.tsx` — replaces current `Scanner.tsx`; queries `/catalogue/search` with debounce
- Filter presets: Technical (RSI, BB, volume), Fundamental (market cap, sector), Liquidity (spread, ADV), Volatility (ATR, HV), Catalyst (earnings, events), Event-risk (macro calendar proximity)
- `quant-app-v1/frontend/src/hooks/useScannerFilters.ts` — persisted filter state in localStorage (migrates to user prefs in Slice 1.4)
- `quant-app-v1/frontend/src/components/features/SavedScreens.tsx` — CRUD for named filter sets (save/load/delete/rename)
- "Open Workspace" button on each result → navigates to `/workspace/{symbol}` with symbol pre-loaded

**Acceptance criteria**
- User creates a saved screen, reloads page, screen persists
- Selecting a result opens instrument workspace with chart + metadata loaded
- Filter presets documented and toggleable

### Slice 1.3: Instrument Workspace & Right Inspector (Week 3–4)
**Depends on:** Slice 1.1 (Canvas/Inspector zones), Phase 0 chart/indicator/pattern components

**Deliverables**
- Center canvas tabs: `Research` (ChartContainer + IndicatorOverlay + PatternList), `Strategy` (placeholder for Phase 3), `Backtest` (placeholder for Phase 3)
- `quant-app-v1/frontend/src/components/features/DecisionInspector.tsx` — right panel showing:
  - Price / change / freshness badge (source, fetched_at, delay)
  - Next macro events (from `/api/v1/calendar` — Phase 2)
  - Signals & confidence (from `/api/v1/analysis` — Phase 0)
  - Paper order preview (symbol, side, qty, est. cost, risk checks — Phase 4)
  - Risk / provenance panel (every data point shows source + timestamp)
- `quant-app-v1/frontend/src/hooks/useWorkspace.ts` — persists layout per symbol (tab, timeframe, indicators, inspector width)
- Empty/loading/error states for every panel (skeletons, "no data", "source unavailable" banners)

**Acceptance criteria**
- Workspace loads with chart, indicators, patterns, forecast tab
- Right inspector shows provenance for every data point
- Layout persists across symbol switches and reloads
- No raw JSON visible

### Slice 1.4: User Preferences & Auth Foundation (Week 4–5)
**Depends on:** Slice 1.1 (Navigation needs auth state), Slice 1.2 (Saved screens migrate to server), Slice 1.3 (Layout prefs migrate to server)

**Decisions needed from user:**
- **Auth model:** JWT + SQLite (local) → PostgreSQL (prod) — *recommended start*; or managed (Clerk / Supabase / Firebase)
- **Storage:** SQLite for local dev; PostgreSQL for production

**Deliverables**
- Backend:
  - `quant-app-v1/backend/app/models/user.py` — `User`, `UserPreferences` (watchlists: `list[Watchlist]`, saved_layouts: `dict[str, Layout]`, theme, default_timezone)
  - `quant-app-v1/backend/app/api/v1/auth.py` — `POST /register`, `POST /login`, `POST /logout`, `GET /me`, `POST /refresh`
  - `quant-app-v1/backend/app/api/v1/watchlists.py` — `GET/POST/PATCH/DELETE /api/v1/watchlists`
  - `quant-app-v1/backend/app/api/v1/layouts.py` — `GET/POST/PATCH/DELETE /api/v1/layouts`
  - `quant-app-v1/backend/app/api/v1/preferences.py` — `GET/PATCH /api/v1/preferences`
- Frontend:
  - `quant-app-v1/frontend/src/hooks/useAuth.ts` — auth context, token storage, auto-refresh
  - `quant-app-v1/frontend/src/components/auth/LoginForm.tsx`, `SignupForm.tsx`
  - `quant-app-v1/frontend/src/components/features/WatchlistManager.tsx` — create/watchlists, add/remove symbols, reorder
  - Migration: localStorage saved screens/layouts → server on first login

**Acceptance criteria**
- User signs up, logs in, creates watchlist, adds symbols, reloads → watchlist persists
- Layout preferences survive logout/login
- No secrets exposed to browser

### Slice 1.5: News/Calendar Cards (Week 5–6)
**Depends on:** Phase 2 Slice 2.2 (calendar/news endpoints) — **TBD: will integrate when Phase 2 delivers**; for now, use Phase 0 `/api/news/forex-factory` with clear "scraped/unreliable" badges

**Deliverables**
- `quant-app-v1/frontend/src/components/features/NewsFeed.tsx` — replaces `NewsTerminal.tsx`; cards with: headline, source, published_at, freshness indicator, impact badge, related instruments (chips), source link
- `quant-app-v1/frontend/src/components/features/EconomicCalendar.tsx` — monthly/weekly/day views; event cards with: title, UTC time → local display, importance