# Quant Application Dashboard

This application provides a real-time, multi-faceted dashboard for quantitative market analysis. It integrates REST API data fetching with live WebSocket streams to provide comprehensive market monitoring.

## Phase 0 operating mode

Gateway currently supports **US-equities research and paper trading only**. Live execution is unavailable in every environment; startup rejects `GATEWAY_EXECUTION_MODE=live`. The legacy Forex Factory route is intentionally unavailable until a licensed structured news/calendar source has been selected.

Start the backend from the repository root:

```sh
pip install -r requirements.txt
export GATEWAY_ENV=local                 # local | test | paper | production
export GATEWAY_EXECUTION_MODE=paper      # required in every profile
export ALPACA_API_KEY=...                # optional; needed for /history
export ALPACA_SECRET_KEY=...
PYTHONPATH=quant-app-v1/backend uvicorn app.main:app --reload --port 8000
```

`GET /health` reports non-secret configured capabilities. Historical candles identify their provider, data timestamp, fetch timestamp, coverage, delay, and entitlement metadata. Without Alpaca credentials, `/history/{ticker}` returns a clear unavailable response instead of substituting data.

Developer tests are declared in `requirements-dev.txt`.

## Key Features
- **Live Charting:** Displays candlestick charts with live updates, technical indicators (RSI), and pattern detection overlays.
- **Data Sources:**
    - **REST API:** Fetches historical data (`/history/:ticker`) and performs symbol searches (`/stocks/search`).
    - **WebSocket:** Maintains a persistent connection (`/ws/trading`) for live price ticks, indicators, and pattern alerts.
- **Modules:**
    - **Scanner:** REST client for searching and selecting market symbols.
    - **ChartContainer:** Orchestrates data flow between history fetching and live socket updates.
    - **News Terminal:** Displays sentiment analysis from the backend.
    - **PatternList:** Visualizes algorithmic trading patterns detected in real-time.

## File Structure Overview
- `src/hooks/useHistory.ts`: Handles REST calls for historical data.
- `src/hooks/useSocket.ts`: Manages the live WebSocket connection and data parsing.
- `src/components/Scanner.tsx`: Handles symbol lookup via REST.
- `src/components/charts/MainChart.tsx`: Renders the primary candlestick chart using Lightweight Charts.
- `src/components/features/PatternList.tsx`: Displays detected trading patterns.
- `src/components/features/NewsTerminal.tsx`: Displays sentiment analysis from the backend.

## Forecasting and portfolio allocation

Gateway now exposes two optional quantitative integrations:

- `POST /forecast/kronos` turns supplied OHLCV chart bars into a probabilistic Kronos forecast. The local base model and tokenizer live in `quant-app-v1/backend/models/kronos/`. Clone [Kronos](https://github.com/shiyu-coder/Kronos), install its requirements, and set `KRONOS_REPO_PATH` to that checkout so Gateway can load its model classes. The endpoint remains unavailable (HTTP 503 with an actionable message) until this is configured; the dashboard itself continues to work.
- `POST /portfolio/optimize` uses [skfolio](https://github.com/skfolio/skfolio) to produce allocations from aligned price data. It supports `hrp` (default) and `mean_risk` methods. Install the project requirements to enable it.

Example allocation request:

```json
{
  "method": "hrp",
  "prices": {
    "AAPL": [190.1, 191.4, 190.7],
    "MSFT": [420.0, 422.3, 421.1]
  }
}
```
