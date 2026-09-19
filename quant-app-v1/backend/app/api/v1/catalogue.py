from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models import Instrument
from app.services.catalogue import (
    InstrumentCatalogueError,
    catalogue_info,
    search_instruments,
)

router = APIRouter(prefix="/catalogue", tags=["catalogue"])


@router.get("")
async def get_catalogue_info() -> dict:
    """Versioned catalogue identity and provenance, without secrets."""
    try:
        return catalogue_info()
    except InstrumentCatalogueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/search")
async def search_catalogue(
    query: str = Query(default="", description="Symbol prefix or name fragment"),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict:
    """Return typed Instrument records from the versioned catalogue."""
    try:
        instruments: list[Instrument] = search_instruments(query, limit=limit)
    except InstrumentCatalogueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "query": query.strip().upper(),
        "matches": [instrument.symbol for instrument in instruments],
        "instruments": [instrument.model_dump(mode="json") for instrument in instruments],
    }