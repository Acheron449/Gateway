from __future__ import annotations

from fastapi import APIRouter

from app.services import market_data

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/search")
async def search_tickers(query: str) -> dict:
    universe = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"]
    matches = [ticker for ticker in universe if query.upper() in ticker]
    return {"query": query, "matches": matches}


@router.get("/{ticker}/metadata")
async def get_ticker_metadata(ticker: str) -> dict:
    df = await market_data.fetch_ohlcv(ticker, limit=2)
    latest = float(df["Close"].iloc[-1])
    return {
        "ticker": ticker.upper(),
        "last_close": latest,
        "currency": "USD",
    }