# Gateway - Quant Application Dashboard

This application provides a real-time, multi-faceted dashboard for quantitative market analysis. It integrates REST API data fetching with live WebSocket streams to provide comprehensive market monitoring.

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

