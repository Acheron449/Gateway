from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from app.providers.registry import get_provider, has_stored_key, list_providers
from app.providers.base import ProviderUnavailableError
from app.services.calendar_service import fetch_and_store_economic_events, get_calendar_provenance
from app.services.news_service import fetch_and_store_news, get_news_provenance


router = APIRouter(prefix="/news", tags=["news"])
quote_router = APIRouter(tags=["market-data"])


def _unavailable_provenance(provider_name: str, provider_version: str, coverage: str, message: str) -> dict:
    return {
        "source": provider_name,
        "provider_version": provider_version,
        "coverage": coverage,
        "entitlement": "unavailable",
        "message": message,
    }


class NewsResponse(BaseModel):
    symbol: Optional[str]
    items: list[dict]
    provenance: dict
    count: int
    status: str = "available"
    message: Optional[str] = None


class CalendarResponse(BaseModel):
    events: list[dict]
    provenance: dict
    count: int
    status: str = "available"
    message: Optional[str] = None


class QuoteResponse(BaseModel):
    instrument: str
    last_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None
    provenance: dict
    status: str = "available"
    message: Optional[str] = None


@router.get("", response_model=NewsResponse)
async def get_news(
    symbol: Optional[str] = Query(None, description="Filter by symbol (e.g., AAPL)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of items"),
    provider: str = Query("Finnhub", description="Data provider"),
    response: Response = None,
) -> NewsResponse:
    """Fetch and persist news headlines with provenance."""
    provider_instance = get_provider(provider)
    if provider_instance is None:
        if response is not None:
            response.status_code = 503
        return NewsResponse(
            symbol=symbol,
            items=[],
            provenance=_unavailable_provenance(provider, "unknown", "US equities news", f"Provider '{provider}' is not available"),
            count=0,
            status="unavailable",
            message=f"Provider '{provider}' is not available",
        )

    if not provider_instance.is_configured:
        message = f"Provider '{provider_instance.name}' is not configured"
        if response is not None:
            response.status_code = 503
        return NewsResponse(
            symbol=symbol,
            items=[],
            provenance=_unavailable_provenance(provider_instance.name, provider_instance.meta["version"], "US equities news", message),
            count=0,
            status="unavailable",
            message=message,
        )

    try:
        items = await fetch_and_store_news(provider_name=provider_instance.name, symbol=symbol, limit=limit)
    except ProviderUnavailableError as exc:
        message = str(exc)
        if response is not None:
            response.status_code = 503
        return NewsResponse(
            symbol=symbol,
            items=[],
            provenance=_unavailable_provenance(provider_instance.name, provider_instance.meta["version"], "US equities news", message),
            count=0,
            status="unavailable",
            message=message,
        )
    return NewsResponse(
        symbol=symbol,
        items=[item.model_dump(mode="json") for item in items],
        provenance=await get_news_provenance(provider_instance.name),
        count=len(items),
    )


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    limit: int = Query(20, ge=1, le=100, description="Maximum number of events"),
    provider: str = Query("Finnhub", description="Data provider"),
    response: Response = None,
) -> CalendarResponse:
    """Fetch and persist economic calendar events with provenance."""
    provider_instance = get_provider(provider)
    if provider_instance is None:
        if response is not None:
            response.status_code = 503
        return CalendarResponse(
            events=[],
            provenance=_unavailable_provenance(provider, "unknown", "US economic calendar", f"Provider '{provider}' is not available"),
            count=0,
            status="unavailable",
            message=f"Provider '{provider}' is not available",
        )

    if not provider_instance.is_configured:
        message = f"Provider '{provider_instance.name}' is not configured"
        if response is not None:
            response.status_code = 503
        return CalendarResponse(
            events=[],
            provenance=_unavailable_provenance(provider_instance.name, provider_instance.meta["version"], "US economic calendar", message),
            count=0,
            status="unavailable",
            message=message,
        )

    try:
        events = await fetch_and_store_economic_events(provider_name=provider_instance.name, limit=limit)
    except ProviderUnavailableError as exc:
        message = str(exc)
        if response is not None:
            response.status_code = 503
        return CalendarResponse(
            events=[],
            provenance=_unavailable_provenance(provider_instance.name, provider_instance.meta["version"], "US economic calendar", message),
            count=0,
            status="unavailable",
            message=message,
        )
    return CalendarResponse(
        events=[event.model_dump(mode="json") for event in events],
        provenance=await get_calendar_provenance(provider_instance.name),
        count=len(events),
    )


@quote_router.get("/quote/{symbol}", response_model=QuoteResponse)
async def get_quote(
    symbol: str,
    provider: str = Query("Finnhub", description="Data provider"),
    response: Response = None,
) -> QuoteResponse:
    """Return a normalized quote without synthetic substitution."""
    provider_instance = get_provider(provider)
    if provider_instance is None:
        message = f"Provider '{provider}' is not available"
        if response is not None:
            response.status_code = 503
        return QuoteResponse(
            instrument=symbol.upper(),
            provenance=_unavailable_provenance(provider, "unknown", "US equities quote", message),
            status="unavailable",
            message=message,
        )
    if not provider_instance.is_configured:
        message = f"Provider '{provider_instance.name}' is not configured"
        if response is not None:
            response.status_code = 503
        return QuoteResponse(
            instrument=symbol.upper(),
            provenance=_unavailable_provenance(provider_instance.name, provider_instance.meta["version"], "US equities quote", message),
            status="unavailable",
            message=message,
        )
    try:
        quote = await provider_instance.quote(symbol)
    except ProviderUnavailableError as exc:
        message = str(exc)
        if response is not None:
            response.status_code = 503
        return QuoteResponse(
            instrument=symbol.upper(),
            provenance=_unavailable_provenance(provider_instance.name, provider_instance.meta["version"], "US equities quote", message),
            status="unavailable",
            message=message,
        )
    if quote is None:
        message = f"Provider '{provider_instance.name}' returned no quote"
        if response is not None:
            response.status_code = 502
        return QuoteResponse(
            instrument=symbol.upper(),
            provenance=_unavailable_provenance(provider_instance.name, provider_instance.meta["version"], "US equities quote", message),
            status="unavailable",
            message=message,
        )
    return QuoteResponse(**quote)


@router.get("/providers")
async def list_provider_statuses() -> dict:
    """List available data providers and their configuration status."""
    providers_info = {}
    for name, meta in list_providers().items():
        provider_instance = get_provider(name)
        providers_info[name] = {
            "meta": meta,
            "configured": bool(provider_instance and provider_instance.is_configured),
            "has_stored_key": has_stored_key(name),
        }
    return {"providers": providers_info}
