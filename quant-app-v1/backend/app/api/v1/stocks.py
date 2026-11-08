from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, HTTPException, Query

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
async def get_ticker_metadata(ticker: str, as_of: datetime | None = None) -> dict:
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise HTTPException(status_code=422, detail="as_of must be timezone-aware")
    try:
        instrument = get_instrument(ticker)
    except InstrumentCatalogueError as exc:
        # Degrade like /stocks/search does when the catalogue is absent
        # instead of surfacing an unhandled 500.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if instrument is None:
        raise HTTPException(status_code=404, detail=f"'{ticker.upper()}' is not in the supported instrument catalogue")
    result = await market_data.fetch_ohlcv(ticker, limit=2, as_of=as_of)
    latest = float(result.dataframe["Close"].iloc[-1])
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