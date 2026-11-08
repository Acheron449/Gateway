
---

#### **`docs/phase-3-plan.md`**
```markdown
# Phase 3 — Strategy Studio & Credible Backtesting (14–22 weeks)

> Status: **Partially verified (2026-10-18).** Strategy specifications and versioned storage exist; canonical versioned content hashing and atomic SQLite version allocation were implemented and focused-tested in this increment. The plan's full Strategy Studio, reproducible backtest receipts, OOS validation, and promotion lifecycle are not thereby complete. Evidence: `quant-app-v1/backend/app/models/__init__.py`, `app/api/v1/strategies.py`, and `quant-app-v1/backend/tests/test_strategy_content_hash.py`.

## User outcome

Natural-language assistance produces a typed, reviewable strategy specification — not an opaque execution plan. User inspects and approves explicit rules before any run. Backtests use realistic costs (commission, spread, slippage, latency, FX, corporate actions), deterministic replay, and produce immutable receipts with OOS validation. Strategy Vault tracks versions with promotion statuses.

## Slices (in dependency order)

### Slice 3.1: Typed Strategy Specification (Week 1–3)
**Depends on:** Phase 0 domain models (`Strategy`, `StrategyVersion`, `BacktestRun`), Phase 1 `DecisionInspector` (paper order preview)

**Deliverables**
- `quant-app-v1/backend/app/models/strategy.py` — `StrategySpec` (immutable, content-addressed):
  ```python
  class StrategySpec(BaseModel):
      asset_universe: list[str]                    # symbols or catalogue query
      timeframe: str                               # "1m", "5m", "1h", "1d"
      entry: EntryRule                             # condition + params
      exit: ExitRule                               # condition + params
      sizing: SizingRule                           # fixed, pct_equity, volatility_target
      invalidation: InvalidationRule               # stop_loss, time_stop, event_stop
      sessions: list[SessionRule]                  # RTH, ETH, specific hours
      event_rules: list[EventRule]                 # avoid/require around events
      assumptions: Assumptions                     # commission, spread, slippage, latency, fx, corp_actions
      labels: dict[str, str]                       # human-readable descriptions