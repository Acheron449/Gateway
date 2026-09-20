"""OpenBB REST API Routes — Surface OpenBB data to frontend / external consumers.

Phase 6 — Slice 6.2: CLI / REST API Wrapper
Feature-gated via ENABLE_OPENBB_DATA (default: false).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.providers.openbb_provider import OpenBBProvider, OpenBBConfig

router = APIRouter(prefix="/openbb", tags=["openbb"])

_openbb_provider: Optional[OpenBBProvider] = None


def get_openbb_provider() -> OpenBBProvider:
    """Get or create OpenBB provider instance."""
    global _openbb_provider
    settings = get_settings()

    if not settings.enable_openbb_data:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OpenBB data integration is disabled. Set ENABLE_OPENBB_DATA=true to enable."
        )

    if _openbb_provider is None:
        _openbb_provider = OpenBBProvider(OpenBBConfig())
    return _openbb_provider


class OHLCVResponse(BaseModel):
    """OHLCV data response model."""
    symbol: str
    timeframe: str
    range: str
    data: List[Dict[str, Any]]
    count: int
    provenance: Dict[str, Any]


class QuoteResponse(BaseModel):
    """Quote response model."""
    symbol: str
    last_price: float
    bid: Optional[float]
    ask: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]
    provenance: Dict[str, Any]


class AvailableProvidersResponse(BaseModel):
    """Available integrations response model."""
    providers: List[Dict[str, Any]]


@router.get("/equity", response_model=OHLCVResponse)
async def get_equity_history(
    symbol: str = Query(..., min_length=1, max_length=12, description="Stock symbol (e.g., AAPL)"),
    interval: str = Query("1d", description="Interval (1d, 1h, 5m, 1m)"),
    period: str = Query("1y", description="Period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)"),
    provider: OpenBBProvider = Depends(get_openbb_provider),
) -> OHLCVResponse:
    """Get historical equity data from OpenBB."""
    try:
        data = await provider.history(symbol=symbol.upper(), interval=interval, range=period)
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No data found for symbol {symbol.upper()}"
            )

        provenance = data[0].get("provenance", {}) if data else {}

        return OHLCVResponse(
            symbol=symbol.upper(),
            timeframe=interval,
            range=period,
            data=data,
            count=len(data),
            provenance=provenance,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch equity data: {str(e)}"
        )


@router.get("/crypto", response_model=OHLCVResponse)
async def get_crypto_history(
    symbol: str = Query(..., min_length=3, max_length=20, description="Crypto symbol (e.g., BTC-USD)"),
    interval: str = Query("1d", description="Interval (1d, 1h, 5m, 1m)"),
    period: str = Query("1y", description="Period (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)"),
    provider: OpenBBProvider = Depends(get_openbb_provider),
) -> OHLCVResponse:
    """Get historical crypto data from OpenBB."""
    try:
        data = await provider.history(symbol=symbol.upper(), interval=interval, range=period)
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No data found for symbol {symbol.upper()}"
            )

        provenance = data[0].get("provenance", {}) if data else {}

        return OHLCVResponse(
            symbol=symbol.upper(),
            timeframe=interval,
            range=period,
            data=data,
            count=len(data),
            provenance=provenance,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch crypto data: {str(e)}"
        )


@router.get("/quote", response_model=QuoteResponse)
async def get_quote(
    symbol: str = Query(..., min_length=1, max_length=20, description="Symbol (e.g., AAPL or BTC-USD)"),
    provider: OpenBBProvider = Depends(get_openbb_provider),
) -> QuoteResponse:
    """Get real-time quote from OpenBB."""
    try:
        quote = await provider.quote(symbol=symbol.upper())
        if quote is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No quote found for symbol {symbol.upper()}"
            )

        return QuoteResponse(**quote)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch quote: {str(e)}"
        )


@router.get("/news", response_model=List[Dict[str, Any]])
async def get_news(
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    limit: int = Query(10, ge=1, le=50, description="Number of news items"),
    provider: OpenBBProvider = Depends(get_openbb_provider),
) -> List[Dict[str, Any]]:
    """Get news from OpenBB."""
    try:
        news = await provider.news(symbol=symbol, limit=limit)
        return [
            {
                "id": item.id,
                "headline": item.headline,
                "url": item.url,
                "source": item.source,
                "published_at": item.published_at.isoformat() if hasattr(item.published_at, 'isoformat') else str(item.published_at),
                "fetched_at": item.fetched_at.isoformat() if hasattr(item.fetched_at, 'isoformat') else str(item.fetched_at),
                "categories": item.categories,
                "related_symbols": item.related_symbols,
                "sentiment_score": item.sentiment_score,
                "provider_version": item.provider_version,
            }
            for item in news
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch news: {str(e)}"
        )


@router.get("/calendar", response_model=List[Dict[str, Any]])
async def get_calendar(
    limit: int = Query(10, ge=1, le=50, description="Number of events"),
    provider: OpenBBProvider = Depends(get_openbb_provider),
) -> List[Dict[str, Any]]:
    """Get economic calendar from OpenBB."""
    try:
        events = await provider.calendar(limit=limit)
        return [
            {
                "id": item.id,
                "title": item.title,
                "country": item.country,
                "currency": item.currency,
                "importance": item.importance.value if hasattr(item.importance, 'value') else str(item.importance),
                "scheduled_at": item.scheduled_at.isoformat() if hasattr(item.scheduled_at, 'isoformat') else str(item.scheduled_at),
                "actual": item.actual,
                "forecast": item.forecast,
                "prior": item.prior,
                "revisions": item.revisions,
                "related_symbols": item.related_symbols,
                "provider_version": item.provider_version,
            }
            for item in events
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch calendar: {str(e)}"
        )


@router.get("/available", response_model=AvailableProvidersResponse)
async def get_available_integrations(
    provider: OpenBBProvider = Depends(get_openbb_provider),
) -> AvailableProvidersResponse:
    """List loaded OpenBB integrations."""
    try:
        import openbb as obb
        integrations = []
        for attr in dir(obb):
            if not attr.startswith("_"):
                integrations.append({
                    "name": attr,
                    "type": "integration",
                })
        return AvailableProvidersResponse(providers=integrations)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list integrations: {str(e)}"
        )