# Phase 0 safety slice

## User outcome

Gateway is explicitly a US-equities research and paper-trading service. Its health endpoint exposes safe capability state, historical candles show provenance, and unsupported/live actions fail visibly rather than silently routing or substituting data.

## Changes

- Added `GATEWAY_ENV` profiles (`local`, `test`, `paper`, `production`) and mandatory `GATEWAY_EXECUTION_MODE=paper`.
- Added non-secret `GET /health` capability reporting.
- Blocked non-paper broker configuration, non-paper Alpaca URLs, and placeholder/invalid order inputs.
- Changed the placeholder orchestrator into research-only signal output.
- Added provenance fields to every historical candle.
- Disabled the scraped Forex Factory endpoint pending a licensed structured provider.

## Intentionally unavailable

Live execution, structured news/calendar data, a durable instrument catalogue, strategy approval, and user workspaces are later roadmap increments.

## Developer migration

Use `requirements-dev.txt` for test dependencies. Set `GATEWAY_EXECUTION_MODE=paper` (or leave its paper default) and configure Alpaca paper credentials only when historical data is needed.
