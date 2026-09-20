"""Calendar service for fetching and storing economic events from providers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models import EconomicEvent, EventImportance
from app.providers import get_provider
from app.services.database import (
    get_economic_events as db_get_economic_events,
    insert_economic_event,
    get_economic_event as db_get_economic_event,
)


async def fetch_and_store_economic_events(
    provider_name: str = "Finnhub",
    limit: int = 50,
) -> List[EconomicEvent]:
    """Fetch economic events from provider and store in database."""
    provider = get_provider(provider_name)
    if not provider or not provider.is_configured:
        return []

    try:
        events = await provider.calendar(limit=limit)
    except Exception:
        return []

    stored_events = []
    now = datetime.now(timezone.utc).isoformat()
    for event in events:
        event_dict = event.model_dump(mode="json")
        event_dict.update({
            "source": provider_name,
            "fetched_at": now,
        })
        insert_economic_event(event_dict)
        stored_events.append(event)

    return stored_events


async def get_economic_events(
    since: str | None = None,
    until: str | None = None,
    countries: List[str] | None = None,
    currencies: List[str] | None = None,
    importance: str | None = None,
    limit: int = 100,
) -> List[EconomicEvent]:
    """Get economic events from database with filters."""
    events_data = db_get_economic_events(
        since=since,
        until=until,
        countries=countries,
        currencies=currencies,
        importance=importance,
        limit=limit,
    )
    return [EconomicEvent(**e) for e in events_data]


async def get_economic_event(event_id: str) -> EconomicEvent | None:
    """Get a single economic event by ID."""
    event_data = db_get_economic_event(event_id)
    if not event_data:
        return None
    return EconomicEvent(**event_data)


async def get_calendar_provenance() -> Dict[str, Any]:
    """Get provenance info for the calendar data source."""
    return {
        "source": "Finnhub",
        "provider_version": "finnhub-v1",
        "coverage": "US economic calendar",
        "entitlement": "configured-provider",
    }


async def get_economic_event_snapshot(event_id: str) -> Dict[str, Any] | None:
    """Get a snapshot of an economic event for backtest reproducibility."""
    from app.services.database import get_event_snapshot
    snapshot = get_event_snapshot(event_id, "finnhub-v1")
    if not snapshot:
        return None
    return snapshot["snapshot_data"]