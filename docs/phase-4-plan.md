
---

#### **`docs/phase-4-plan.md`**
```markdown
# Phase 4 — Paper Portfolios, Risk & Review (22–30 weeks)

## User outcome

Continuous paper trading with complete reconciliation. Every fill traceable from journal entry → strategy version → data snapshot → risk decision → order lifecycle. Server-side risk controls cannot be bypassed. Kill switch tested and instant.

## Slices (in dependency order)

### Slice 4.1: Paper Portfolio Ledger (Week 1–4)
**Depends on:** Phase 0 `Order`/`Fill`/`Portfolio` models, Phase 1 WebSocket infrastructure (**TBD**), Phase 3 backtest engine (for paper-vs-backtest comparison)

**Deliverables**
- Database tables (Alembic):
  - `portfolios`: `id`, `user_id`, `cash`, `equity`, `buying_power`, `created_at`, `updated_at`
  - `positions`: `id`, `portfolio_id`, `instrument_id`, `quantity`, `avg_cost`, `market_value`, `unrealized_pnl`, `realized_pnl`
  - `orders`: `id`, `portfolio_id`, `strategy_version_id`, `instrument_id`, `side`, `type`, `qty`, `limit_price`, `stop_price`, `status`, `filled_qty`, `avg_fill_price`, `created_at`, `updated_at`
  - `fills`: `id`, `order_id`, `instrument_id`, `side`, `qty`, `price`, `commission`, `timestamp`, `liquidity` (maker/taker)
  - `cash_ledger`: `id`, `portfolio_id`, `amount`, `type` (deposit/withdrawal/fill/commission/dividend/interest), `ref_id`, `ref_type`, `timestamp`
- `quant-app-v1/backend/app/services/paper_portfolio.py` — canonical event sourcing:
  - Events: `OrderSubmitted` → `OrderAcknowledged` → `Fill` (partial/full) → `PositionUpdate` → `CashUpdate`
  - `apply_event(event)` — pure function, deterministic replay
  - `reconstruct_portfolio(portfolio_id, as_of_timestamp)` — rebuilds state from event log
- API:
  - `GET /api/v1/portfolio` — current positions, cash, P&L, open orders, recent fills
  - `GET /api/v1/portfolio/history` — equity curve, cash flows
  - **TBD: WebSocket** — `ws://host/api/v1/portfolio/stream` — real-time pushes for fills, position updates, risk alerts
- Frontend: `PaperTrading.tsx` — portfolio dashboard, order entry form (validated by risk engine), fill history

**Acceptance criteria**
- Portfolio state reconstructible from event log (replay test passes)
- WebSocket pushes match HTTP snapshots (integration test)
- No negative cash without margin enabled

### Slice 4.2: Server-Side Risk Controls (Week 4–7)
**Depends on:** Slice 4.1 (portfolio state), Phase 0 `RiskConfig`/`RiskManager`, Phase 2 calendar (event blackouts)

**Deliverables**
- `quant-app-v1/backend/app/services/risk_engine.py` — pre-trade checks (all in `POST /api/v1/orders` before acceptance):
  - **Buying power**: `cash + margin - reserved` ≥ `order_value`
  - **Concentration**: max % per instrument (default 10%), sector (20%), asset class (50%)
  - **Gross/net exposure**: gross ≤ 2× equity, net ≤ 1× equity (configurable)
  - **Daily loss limit**: realized + unrealized P&L ≤ -X% equity → kill switch
  - **Instrument restrictions**: blocklist (configurable via env/db)
  - **Event blackout**: no new orders ±N minutes around high