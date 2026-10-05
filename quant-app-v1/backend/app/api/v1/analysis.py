from __future__ import annotations

from fastapi import APIRouter

from app.api.nlp import sentiment
from app.quant import impact_model, recognition, technicals
from app.services import market_data

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/{ticker}")
async def get_analysis(ticker: str) -> dict:
    ohlcv_result = await market_data.fetch_ohlcv(ticker)
    df = ohlcv_result.dataframe
    provenance = ohlcv_result.provenance
    df_indicators = technicals.calculate_all_indicators(df)
    pivots = recognition.find_pivots(df_indicators)
    patterns = [signal.to_dict() for signal in recognition.detect_head_and_shoulders(pivots)]
    news_score = sentiment.get_latest_score_for_ticker(ticker)
    final = impact_model.calculate_final_signal(patterns, news_score)

    return {
        "ticker": ticker.upper(),
        "price": float(df_indicators["Close"].iloc[-1]),
        "rsi": float(df_indicators["RSI"].iloc[-1]),
        "signals": patterns,
        "overall_confidence": final["confidence"],
        "direction": final["direction"],
        "provenance": provenance,
    }
