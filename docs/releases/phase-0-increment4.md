# Phase 0 — increment 4 (final): risk limits, indicators, backtest lifecycle, order guards

Closes the Phase 0 plan item **"unit tests for normalization, indicators, risk
limits, backtest lifecycle and order guards"** as the fourth and last Phase 0
slice. Like catalogue/boundary/safety before it, this slice is **offline,
typed and dependency-free** — deterministic synthetic bars, no broker, no
network, no `users.db`, no new imports, CI runs it on every push.

## What ships in this increment

* **Indicators (`app/quant/technicals`)** — `calculate_rsi` and
  `calculate_bollinger_bands` asserted on 64 deterministic offline bars:
  RSI stays finite and bounded in `[0, 100]` once warmed, and the Bollinger
  envelope never inverts (`lower ≤ mid ≤ upper`).
* **Risk limits (`app/quant/risk_manager`)** — the shipped `RiskConfig`
  (2% max per-trade risk, 20% max total exposure) and `RiskManager` sizing
  asserted byte-exact against the shipped formula
  `capital × max_portfolio_risk / (volatility + 1e-6)`; exposure validation
  rejects any single trade/current+new combination past total capital.
* **Backtest lifecycle (`app/quant/backtest` + `app/models`)** — a typed
  `BacktestRun` is created for **every** shipped `BacktestRunStatus`
  (`queued`, `running`, `completed`, `failed`); each record carries a typed
  `provenance` (source/provider-version/coverage/UTC lifecycle times), and the
  suite asserts the **full shipped status progression** rather than a
  placeholder two-state subset.
* **Order guards (paper-only)** — every shipped `Order` record stays within
  the paper envelope (no live/placeholder-side orders may progress), matching
  the earlier safety slice but now exercising the indicator/risk/lifecycle
  math those slices only probed in passing.

## Test count

Phase 0 closes at **36 passing offline tests** across the four slices
(`test_phase0_boundary`, `test_phase0_catalogue`, `test_phase0_safety`,
`test_phase0_increment4`) — with the single pre-existing integration failure
(`tests/test_integration.py::test_recognition_engine_patterns`) still
untouched and documented as out-of-scope for Phase 0.

## Files

* `backend/tests/test_phase0_increment4.py` — the lifecyle/risk/indicator slice.

## Run

```bash
cd quant-app-v1/backend && PYTHONPATH=. python -m pytest tests/test_phase0_increment4.py -q
```

## Gate

CI runs this increment with the catalogue/boundary/safety slices on every push;
nothing here requires credentials, a broker, or the legacy Flask tree.
