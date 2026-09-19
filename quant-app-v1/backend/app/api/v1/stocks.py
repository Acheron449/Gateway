from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import market_data
from app.services.catalogue import InstrumentCatalogueError, get_instrument, search_instruments

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("/search")
async def search_tickers(query: str) -> dict:
    """Symbol lookup backed by the versioned instrument catalogue.

    ``matches`` keeps symbols for backward compatibility; ``instruments``
    carries the typed records with catalogue provenance. Unknown symbols return
    an empty result rather than fabricating a match.
    """
    try:
        instruments = search_instruments(query)
    except InstrumentCatalogueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "query": query.strip().upper(),
        "matches": [instrument.symbol for instrument in instruments],
        "instruments": [instrument.model_dump(mode="json") for instrument in instruments],
    }


@router.get("/{ticker}/metadata")
async def get_ticker_metadata(ticker: str) -> dict:
    instrument = get_instrument(ticker)
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"'{ticker.upper()}' is not in the supported instrument catalogue")
    df = await market_data.fetch_ohlcv(ticker, limit=2)
    latest = float(df["Close"].iloc[-1])
    return {
        "ticker": instrument.symbol,
        "name": instrument.name,
        "exchange": instrument.exchange,
        "asset_class": instrument.asset_class.value,
        "instrument_type": instrument.instrument_type.value,
        "currency": instrument.currency,
        "last_close": latest,
        "provenance": instrument.provenance.model_dump(mode="json"),
    }