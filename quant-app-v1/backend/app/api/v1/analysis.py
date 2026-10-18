from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, HTTPException

from app.services.as_of import normalize_as_of

from app.api.nlp import sentiment
from app.quant import impact_model, recognition, technicals
from app.services import market_data

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/{ticker}")
async def get_analysis(ticker: str, as_of: datetime | None = None) -> dict:
    try:
        as_of = normalize_as_of(as_of)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if as_of is None:
        ohlcv_result = await market_data.fetch_ohlcv(ticker)
    else:
        ohlcv_result = await market_data.fetch_ohlcv(ticker, as_of=as_of)
    df = ohlcv_result.dataframe
    provenance = ohlcv_result.provenance
    df_indicators = technicals.calculate_all_indicators(df)
    pivots = recognition.find_pivots(df_indicators)
    patterns = [signal.to_dict() for signal in recognition.detect_head_and_shoulders(pivots)]
    news_score = (
        sentiment.get_latest_score_for_ticker(ticker)
        if as_of is None
        else sentiment.get_latest_score_for_ticker(ticker, as_of=as_of)
    )
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
