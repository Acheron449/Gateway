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


# Economic-calendar sources in preference order for provider="auto".
# EconomicCalendar is the default base feed; the rest layer events on top.
_CALENDAR_CHAIN = ("EconomicCalendar", "FinancialModelingPrep", "JBlanked", "Bloomberg", "Finnhub")

_CALENDAR_SOURCE_DETAILS = {
    "EconomicCalendar": "Default economic-calendar-api feed (investing.com) · self-hosted · no API key",
    "FinancialModelingPrep": "Financial Modeling Prep economics calendar · API key · FMP_API_KEY",
    "JBlanked": "Official JBlanked API · ForexFactory · MQL5 · FxStreet feeds · API key required",
    "Bloomberg": "bloomberg.com economic calendar (Investing.com widget) · no API key · may be bot-walled",
    "Finnhub": "Finnhub economic calendar · API key · premium-gated",
}

# News sources in preference order for provider="auto".  Finnhub answers when
# a key is stored; Yahoo Finance (yfinance) is the keyless fallback so the
# panels still fill when Finnhub is unconfigured, gated, or down.
_NEWS_CHAIN = ("Finnhub", "Yahoo Finance")

_NEWS_SOURCE_DETAILS = {
    "Finnhub": "Finnhub company news · API key · free tier",
    "Yahoo Finance": "Yahoo Finance headlines via yfinance · no API key",
}

_NEWS_COVERAGE = "US equities news"


@router.get("", response_model=NewsResponse)
async def get_news(
    symbol: Optional[str] = Query(None, description="Filter by symbol (e.g., AAPL)"),
    limit: int = Query(10, ge=1, le=50, description="Maximum number of items"),
    provider: str = Query(
        "auto",
        description="News source: 'auto' walks the source chain (Finnhub → Yahoo Finance), or name one explicitly",
    ),
    response: Response = None,
) -> NewsResponse:
    """Fetch and persist news headlines with provenance.

    ``provider=auto`` (the default) tries each source in ``_NEWS_CHAIN`` and
    returns the first that answers with stories, mirroring the calendar's
    chain behaviour.  An explicitly named provider is used strictly — its
    failure is reported rather than silently substituted.
    """
    requested = (provider or "auto").strip()
    if requested.casefold() == "auto":
        order: list[str] = list(_NEWS_CHAIN)
    else:
        order = [requested]

    reasons: list[str] = []
    empty_source: Optional[str] = None
    fail_name, fail_version = requested, "unknown"
    for candidate in order:
        instance = get_provider(candidate)
        if instance is None:
            reasons.append(f"{candidate}: not available")
            continue
        if fail_version == "unknown":
            fail_name, fail_version = instance.name, instance.meta.get("version", "unknown")
        if not instance.is_configured:
            reasons.append(f"{instance.name}: not configured")
            continue
        try:
            items = await fetch_and_store_news(provider_name=instance.name, symbol=symbol, limit=limit)
        except ProviderUnavailableError as exc:
            reasons.append(f"{instance.name}: {exc}")
            continue
        if items:
            return NewsResponse(
                symbol=symbol,
                items=[item.model_dump(mode="json") for item in items],
                provenance=await get_news_provenance(instance.name),
                count=len(items),
            )
        reasons.append(f"{instance.name}: no stories returned")
        if empty_source is None:
            empty_source = instance.name

    message = "; ".join(reasons) or "No news sources are configured"
    if empty_source is not None:
        # A configured source answered but produced no rows — keep the
        # empty-success contract so callers can render an empty feed.
        return NewsResponse(
            symbol=symbol,
            items=[],
            provenance=await get_news_provenance(empty_source),
            count=0,
            status="available",
            message=message,
        )
    if response is not None:
        response.status_code = 503
    return NewsResponse(
        symbol=symbol,
        items=[],
        provenance=_unavailable_provenance(fail_name, fail_version, _NEWS_COVERAGE, message),
        count=0,
        status="unavailable",
        message=message,
    )


@router.get("/sources")
async def news_sources() -> dict:
    """List news sources and availability for the news panels' picker."""
    sources = []
    for name in _NEWS_CHAIN:
        instance = get_provider(name)
        meta = list_providers().get(name)
        available = bool(instance and instance.is_configured)
        sources.append(
            {
                "id": name,
                "name": name,
                "detail": _NEWS_SOURCE_DETAILS.get(name, ""),
                "available": available,
                "requires_api_key": bool(meta and meta.get("requires_api_key")),
            }
        )
    return {"sources": sources, "default": "auto", "chain": list(_NEWS_CHAIN)}


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    limit: int = Query(20, ge=1, le=100, description="Maximum number of events"),
    provider: str = Query("auto", description="Calendar source: 'auto' merges the default + all sources, or name one explicitly"),
    response: Response = None,
) -> CalendarResponse:
    """Fetch economic calendar events with a merged multi-source feed.

    ``provider=auto`` (the default) uses the default EconomicCalendar feed as
    the base and layers every other configured source's events on top,
    de-duplicating by (title, time, currency). An explicitly named provider is
    used strictly — its failure is reported instead of silently substituted.
    Provenance names the base source plus any contributors.
    """
    requested = (provider or "auto").strip()
    merged: dict[tuple[str, str, str], dict] = {}
    reasons: list[str] = []
    answered: list[str] = []
    empty_source: Optional[str] = None
    fail_name, fail_version = requested, "unknown"

    if requested.casefold() == "auto":
        order: list[str] = list(_CALENDAR_CHAIN)
    else:
        order = [requested]

    for candidate in order:
        instance = get_provider(candidate)
        if instance is None:
            reasons.append(f"{candidate}: not available")
            continue
        if fail_version == "unknown":
            fail_name, fail_version = instance.name, instance.meta.get("version", "unknown")
        if not instance.is_configured:
            reasons.append(f"{instance.name}: not configured")
            continue
        try:
            events = await fetch_and_store_economic_events(provider_name=instance.name, limit=limit)
        except ProviderUnavailableError as exc:
            reasons.append(f"{instance.name}: {exc}")
            continue
        if events:
            answered.append(instance.name)
            for event in events:
                key = (
                    event.title.strip().casefold(),
                    event.scheduled_at.isoformat(),
                    str(event.currency or "").upper(),
                )
                # Base (first in chain) wins; later sources only add new rows.
                merged.setdefault(key, event.model_dump(mode="json"))
        else:
            reasons.append(f"{instance.name}: no events returned")
            if empty_source is None:
                empty_source = instance.name

    if merged:
        rows = sorted(merged.values(), key=lambda row: row.get("scheduled_at") or "")[: max(1, limit)]
        base = answered[0] if answered else requested
        provenance = await get_calendar_provenance(base)
        if len(answered) > 1:
            provenance["coverage"] = f"Merged economic calendar ({', '.join(answered)})"
        return CalendarResponse(events=rows, provenance=provenance, count=len(rows), status="available")

    message = "; ".join(reasons) or "No calendar sources are configured"
    if empty_source is not None:
        # A configured source answered but produced no rows — keep the
        # empty-success contract so callers can render an empty calendar.
        return CalendarResponse(
            events=[],
            provenance=await get_calendar_provenance(empty_source),
            count=0,
            status="available",
            message=message,
        )
    if response is not None:
        response.status_code = 503
    return CalendarResponse(
        events=[],
        provenance=_unavailable_provenance(fail_name, fail_version, "US economic calendar", message),
        count=0,
        status="unavailable",
        message=message,
    )


@router.get("/calendar/sources")
async def calendar_sources() -> dict:
    """List economic-calendar sources and availability for the Calendar UI."""
    sources = []
    for name in _CALENDAR_CHAIN:
        instance = get_provider(name)
        meta = list_providers().get(name)
        available = bool(instance and instance.is_configured)
        sources.append(
            {
                "id": name,
                "name": name,
                "detail": _CALENDAR_SOURCE_DETAILS.get(name, ""),
                "available": available,
                "requires_api_key": bool(meta and meta.get("requires_api_key")),
            }
        )
    return {"sources": sources, "default": "auto", "chain": list(_CALENDAR_CHAIN)}


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
    # Providers return different payload shapes (Yahoo sends symbol/price,
    # Finnhub sends instrument/last_price). Normalize to the QuoteResponse
    # contract so a mismatched payload degrades instead of raising a pydantic
    # ValidationError (HTTP 500) inside response serialization.
    payload = dict(quote)
    payload.setdefault("instrument", payload.pop("symbol", None) or symbol.upper())
    if payload.get("last_price") is None and "price" in payload:
        payload["last_price"] = payload.pop("price")
    payload.setdefault(
        "provenance",
        {
            "source": provider_instance.name,
            "provider_version": provider_instance.meta.get("version", "unknown"),
            "coverage": "US equities quote",
            "entitlement": "unknown",
        },
    )
    return QuoteResponse(**payload)


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
