from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.provider_registry import get_provider

router = APIRouter(prefix="/news", tags=["news"])


class NewsResponse(BaseModel):
    symbol: Optional[str]
    items: list[dict]
    provenance: dict
    count: int


class CalendarResponse(BaseModel):
    events: list[dict]
    provenance: dict
    count: int


@router.get("", response_model=NewsResponse)
async def get_news(
    symbol: Optional[str] = Query(None, description="Filter by symbol (e.g., AAPL)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of items"),
    provider: str = Query("Finnhub", description="Data provider"),
) -> NewsResponse:
    """Fetch news headlines with provenance."""
    provider_instance = get_provider(provider)
    if not provider_instance:
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider}' not available or not configured",
        )

    if not provider_instance.is_configured:
        return NewsResponse(
            symbol=symbol,
            items=[],
            provenance={
                "source": provider,
                "provider_version": provider_instance.meta.get("version", "unknown"),
                "coverage": "us-equities-news",
                "entitlement": "unavailable",
                "message": f"Provider '{provider}' not configured with API key",
            },
            count=0,
        )

    items = await provider_instance.news(symbol=symbol, limit=limit)
    return NewsResponse(
        symbol=symbol,
        items=[item.model_dump(mode="json") for item in items],
        provenance={
            "source": provider,
            "provider_version": provider_instance.meta.get("version", "unknown"),
            "coverage": "us-equities-news",
            "entitlement": "finnhub-free-tier" if provider_instance.is_configured else "unavailable",
        },
        count=len(items),
    )


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    limit: int = Query(20, ge=1, le=100, description="Maximum number of events"),
    provider: str = Query("Finnhub", description="Data provider"),
) -> CalendarResponse:
    """Fetch economic calendar events with provenance."""
    provider_instance = get_provider(provider)
    if not provider_instance:
        raise HTTPException(
            status_code=503,
            detail=f"Provider '{provider}' not available or not configured",
        )

    if not provider_instance.is_configured:
        return CalendarResponse(
            events=[],
            provenance={
                "source": provider,
                "provider_version": provider_instance.meta.get("version", "unknown"),
                "coverage": "us-equities-calendar",
                "entitlement": "unavailable",
                "message": f"Provider '{provider}' not configured with API key",
            },
            count=0,
        )

    events = await provider_instance.calendar(limit=limit)
    return CalendarResponse(
        events=[event.model_dump(mode="json") for event in events],
        provenance={
            "source": provider,
            "provider_version": provider_instance.meta.get("version", "unknown"),
            "coverage": "us-equities-calendar",
            "entitlement": "finnhub-free-tier" if provider_instance.is_configured else "unavailable",
        },
        count=len(events),
    )


@router.get("/providers")
async def list_providers() -> dict:
    """List available data providers and their configuration status."""
    from app.services.provider_registry import _PROVIDERS, _read_api_key

    providers_info = {}
    for name, provider_class in _PROVIDERS.items():
        # Create a temporary instance to check meta
        temp_provider = provider_class(api_key="")
        api_key = _read_api_key(name)
        is_configured = bool(api_key and api_key.strip())

        providers_info[name] = {
            "meta": temp_provider.meta,
            "configured": is_configured,
        }

    return {"providers": providers_info}