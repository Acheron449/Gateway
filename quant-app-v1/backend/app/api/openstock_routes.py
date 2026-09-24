"""OpenStock symbol lookup and Adanos sentiment routes.

Phase 1-1.5 / Phase 2 extension: expose OpenStock's Finnhub-backed symbol search
and the optional Adanos sentiment endpoint through the Gateway provider layer.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.providers.registry import get_provider

router = APIRouter(prefix="/openstock", tags=["openstock"])


class SymbolSearchResponse(BaseModel):
    query: str
    exchange: str
    matches: list[str]
    instruments: list[dict[str, Any]]


class SentimentResponse(BaseModel):
    symbol: str
    sentiment: dict[str, Any]
    provenance: dict[str, Any]


@router.get("/search", response_model=SymbolSearchResponse)
async def search_symbols(
    query: str = Query(..., min_length=1, description="Symbol or company name fragment"),
    exchange: str = Query("US", description="Exchange code (US, LSE, TSX, NSE, ...)"),
    limit: int = Query(20, ge=1, le=50),
) -> SymbolSearchResponse:
    """Search symbols via the OpenStock provider (Finnhub /stock/symbol)."""
    provider = get_provider("OpenStock")
    if provider is None or not provider.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenStock provider is not configured. Set a Finnhub API key.",
        )
    try:
        instruments = await provider.search(query, exchange=exchange, limit=limit)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Symbol search failed: {exc}",
        ) from exc
    return SymbolSearchResponse(
        query=query.strip().upper(),
        exchange=exchange.upper(),
        matches=[i.symbol for i in instruments],
        instruments=[i.model_dump(mode="json") for i in instruments],
    )


@router.get("/sentiment/{symbol}", response_model=SentimentResponse)
async def get_sentiment(symbol: str) -> SentimentResponse:
    """Fetch structured cross-source sentiment for a symbol via Adanos."""
    provider = get_provider("Adanos")
    if provider is None or not provider.is_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Adanos sentiment provider is not configured. Set ADANOS_API_KEY.",
        )
    try:
        payload = await provider.sentiment(symbol)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Sentiment fetch failed: {exc}",
        ) from exc
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No sentiment data for {symbol.upper()}",
        )
    return SentimentResponse(
        symbol=symbol.upper(),
        sentiment=payload,
        provenance={
            "source": "adanos",
            "provider_version": provider.meta["version"],
            "coverage": "cross-source-sentiment",
            "entitlement": "optional-provider",
        },
    )
