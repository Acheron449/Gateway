Quant App — Implementation & Runbook (.prompt.md)

Summary
-------
This document captures the recent work performed to create a functioning, testable backtesting platform and a multi-provider BrokerService with Finnhub fallback. It describes what was implemented, configuration and run instructions, usage examples, limitations, and recommended next steps so you can decide which direction to take next.

What was implemented
--------------------
1) Risk Management
   - File: quant-app-v1/backend/app/quant/risk_manager.py
   - Implemented RiskConfig and RiskManager:
     - calculate_position_size(current_price, volatility)
     - get_exit_levels(entry_price, direction) -> stop_loss / take_profit
     - validate_exposure(current_exposure, new_trade_value)
   - Uses a simple fixed-fraction approach by default (configurable via RiskConfig).

2) Impact Model (Signal Generation)
   - File: quant-app-v1/backend/app/quant/impact_model.py
   - calculate_final_signal(patterns, sentiment_score)
     - Picks best pattern by confidence and adjusts by sentiment.
     - Returns: { confidence: float, direction: 'Bullish'|'Bearish'|'Neutral' }

3) Backtesting Engine (history-driven)
   - File: quant-app-v1/backend/app/engine/backtester.py
   - BacktestEngine.run_simulation(historical_df, broker: Optional[BrokerService])
     - Iterates historical bars (Timestamp, Price, Sentiment_Score, Pattern_Features)
     - Generates signals using calculate_final_signal
     - Sizes positions via RiskManager
     - Places orders through BrokerService (if provided) and uses provider fill price when available
     - Tracks single open position at a time (entry, SL/TP checks, exit, PnL) and updates current_capital
     - Closes any remaining open position at series end
   - analyze_results(trade_logs) returns simple KPIs + trade log
   - Example usage provided in file header (uses asyncio.run())

4) BrokerService with multi-provider support and Finnhub fallback
   - File: quant-app-v1/backend/app/services/broker_service.py
   - Providers implemented:
     - _AlpacaProvider: uses aiohttp to call Alpaca REST for orders (requires aiohttp + Alpaca keys)
     - _FinnhubProvider: uses Finnhub /quote to pick a realistic fill price and persists simulated orders in-memory
   - BrokerService behavior:
     - Picks provider automatically: Alpaca preferred (if keys and aiohttp present), else Finnhub simulation, else local fallback
     - place_order() attempts provider.place_order(); if it fails and Finnhub is available, tries Finnhub as a fallback
     - get_order_status() returns ExecutionReport with avg_price and executed_qty when available (or simulated filled report as fallback)
   - Enables backtester to use the same execution path used in live flows (when Alpaca is available) or realistic simulated fills (Finnhub fallback)

5) Websocket / Live Feed fallback (Finnhub)
   - File: quant-app-v1/backend/app/api/main.py
   - The app's lifespan now:
     - Uses Alpaca streamer when Alpaca creds present
     - Else, if FINNHUB_API_KEY present, polls Finnhub quote endpoint to produce price+RSI payload for /ws/trading
     - Else uses the synthetic random walker feeder (unchanged)

Files changed or created
------------------------
- quant-app-v1/backend/app/quant/risk_manager.py  (RiskManager)
- quant-app-v1/backend/app/quant/impact_model.py  (existing model; confirmed)
- quant-app-v1/backend/app/engine/backtester.py   (enhanced to use BrokerService and realistic fill prices)
- quant-app-v1/backend/app/services/broker_service.py (Alpaca provider, Finnhub simulated provider, provider selection)
- quant-app-v1/backend/app/api/main.py (Finnhub feed fallback added)

Configuration & Environment variables
-------------------------------------
- ALPACA_API_KEY, ALPACA_SECRET (or ALPACA_KEY / ALPACA_API_SECRET):
  - When present and aiohttp is installed in the backend environment, the app will try to use Alpaca for order placement and the /ws/trading Alpaca stream (live mode).
- ALPACA_BASE_URL (optional): default: https://paper-api.alpaca.markets
- FINNHUB_API_KEY:
  - When ALPACA_* keys are absent, the app will use FINNHUB_API_KEY to poll Finnhub /quote and generate the live feed for the frontend and simulated fills for BrokerService.
- QUANT_WS_SYMBOL (optional): which symbol the /ws/trading feed will subscribe to (default AAPL)
- If you want Alpaca execution, install aiohttp in the backend venv:
  - pip install aiohttp

How to run a quick historical backtest (example)
------------------------------------------------
1) Activate backend venv:
   cd quant-app-v1/backend
   source .venv/bin/activate  # or your environment activation

2) Create a simple script (scripts/run_backtest.py) with this body (or run interactively):

from datetime import datetime
import pandas as pd
import asyncio
from app.engine.backtester import BacktestEngine
from app.quant.risk_manager import RiskConfig
from app.services.broker_service import BrokerService

# tiny sample dataset (replace with actual historical bars)
data = {
    'Timestamp': [datetime(2026,9,15), datetime(2026,9,16)],
    'Price': [150.0, 152.0],
    'Sentiment_Score': [0.5, -0.3],
    'Pattern_Features': [
        [{"pattern":"Moving_Avg_Cross","confidence":0.7,"direction":"Bullish"}],
        [{"pattern":"Mean_Reversion","confidence":0.8,"direction":"Bearish"}],
    ]
}
df = pd.DataFrame(data)

broker = BrokerService()  # will auto-select provider per env config
engine = BacktestEngine(initial_capital=100000.0, risk_config=RiskConfig())
results = asyncio.run(engine.run_simulation(df, broker=broker))
print(engine.analyze_results(results))

3) Run the script:
   python -m scripts.run_backtest

Note: if you do not create a scripts/ folder, run via a Python REPL or small .py file at repo path.

How frontend integration (live vs historical) works
-------------------------------------------------
- The frontend expects a WebSocket at /ws/trading that emits JSON payloads like:
  { "symbol": "AAPL", "price": 151.23, "rsi": 58.12 }
- Backend choices:
  - Live (Alpaca stream) when Alpaca creds present: uses Alpaca StockDataStream to push minute bars to data_queue.
  - Finnhub polling: when Alpaca creds missing but FINNHUB_API_KEY present, backend polls Finnhub /quote and computes an RSI from the rolling buffer to push to data_queue.
  - Synthetic feeder: if neither provider configured, a random-synthetic feeder produces price + RSI for development.
- The backtester uses historical data via the run_simulation API and optionally reuses BrokerService for fills.
  This means the same BrokerService abstraction is used in both live streaming and historical run modes (production-friendly design).

Limitations & assumptions
-------------------------
- Single-position backtester: current backtester holds one open trade at a time. If you need portfolio-level or multi-symbol concurrent positions, extend the bookkeeping to allow multiple open positions.
- Fill model simplifications:
  - Alpaca provider assumes synchronous instant fills via get_order_status (real-world order lifecycle is more complex).
  - Finnhub provider simulates fills using the latest quote and stores orders in memory for the process lifetime; persistent order store is not implemented.
- RiskManager uses simple fixed-fraction sizing. If you want Kelly or other advanced sizing, update calculate_position_size accordingly.
- No fees/slippage model yet — these should be added for realistic backtest results.
- Rate limits: Finnhub polling is naive — production should include rate-limit handling and exponential backoff.

Suggested next steps (pick any):
-------------------------------
- Add multi-position portfolio support and exposure checks (recommended if you want realistic portfolio backtests).
- Add slippage, commissions, and partial-fill simulation to BrokerService and BacktestEngine.
- Add a REST API endpoint (POST /v1/backtest) to submit a historical run job and return job ID + results for frontend visualization.
- Add unit tests for BrokerService provider fallback logic and BacktestEngine trade lifecycle.
- Persist simulated orders to a small local DB (sqlite) to allow cross-process inspections and durable simulation runs.
- Add CLI wrapper to easily run CSV-based backtests (e.g., bin/backtest --csv data.csv --initial-capital 100000).

Files changed (quick list)
-------------------------
- quant-app-v1/backend/app/quant/risk_manager.py  (new/updated)
- quant-app-v1/backend/app/quant/impact_model.py  (existing, used as-is)
- quant-app-v1/backend/app/engine/backtester.py   (updated to use BrokerService and manage SL/TP)
- quant-app-v1/backend/app/services/broker_service.py (updated: Alpaca + Finnhub provider selection + in-memory simulated orders)
- quant-app-v1/backend/app/api/main.py (updated: Finnhub feeder fallback for /ws/trading)

If you want me to continue (I can proceed autonomously):
- Implement multi-position/portfolio backtest support and reorder management.
- Add /v1/backtest endpoint so the frontend can request a historical run and receive summarized results and trade logs for visualization.
- Add slippage/fee model and partial-fill handling in BrokerService.
- Add small persistence (sqlite) for simulated orders and backtests so runs are auditable and repeatable.

Choose which of the above you want next, or say "implement all" and I will proceed in order (I will start with multi-position/portfolio support, then backtest API endpoint, then slippage/fees, then persistence).

-- End of prompt
