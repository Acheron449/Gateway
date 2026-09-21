"""Calendar persistence service for canonical provider records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import EconomicEvent
from app.providers import get_provider
from app.services.database import (
    get_economic_event as db_get_economic_event,
    get_economic_events as db_get_economic_events,
    get_event_snapshot,
    get_event_tags,
    insert_economic_event,
    insert_event_tags,
    store_event_snapshot,
)


def _event_tags(event: EconomicEvent) -> list[dict[str, Any]]:
    tags: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for symbol in event.related_symbols:
        key = ("instrument", symbol.upper())
        if key not in seen:
            seen.add(key)
            tags.append({"tag_type": "instrument", "tag_value": symbol.upper(), "confidence": 1.0, "model_version": "gateway-mapping-v1"})
    for tag_type, value in (("currency", event.currency), ("country", event.country)):
        key = (tag_type, str(value))
        if key not in seen:
            seen.add(key)
            tags.append({"tag_type": tag_type, "tag_value": str(value), "confidence": 1.0, "model_version": "gateway-mapping-v1"})
    return tags


async def fetch_and_store_economic_events(
    provider_name: str = "Finnhub",
    limit: int = 50,
) -> list[EconomicEvent]:
    """Fetch, tag, snapshot, and persist economic calendar events."""
    provider = get_provider(provider_name)
    if not provider or not provider.is_configured:
        return []

    events = await provider.calendar(limit=limit)

    fetched_at = datetime.now(timezone.utc).isoformat()
    stored_events: list[EconomicEvent] = []
    for event in events:
        event.tags = _event_tags(event)
        event.source = provider.name
        event.provider_version = provider.meta["version"]
        event.fetched_at = datetime.fromisoformat(fetched_at)
        event.entitlement = "finnhub-free-tier" if provider.name == "Finnhub" else event.entitlement
        event_dict = event.model_dump(mode="json")
        event_dict["fetched_at"] = fetched_at
        insert_economic_event(event_dict)
        store_event_snapshot(event.id, "economic_event", event_dict, provider.meta["version"])
        insert_event_tags(event.id, "economic_event", event.tags)
        stored_events.append(event)
    return stored_events


async def get_economic_events(
    since: str | None = None,
    until: str | None = None,
    countries: list[str] | None = None,
    currencies: list[str] | None = None,
    importance: str | None = None,
    limit: int = 100,
) -> list[EconomicEvent]:
    """Get persisted economic events with derived tags."""
    rows = db_get_economic_events(
        since=since,
        until=until,
        countries=countries,
        currencies=currencies,
        importance=importance,
        limit=limit,
    )
    events: list[EconomicEvent] = []
    for row in rows:
        row["tags"] = get_event_tags(row["id"], "economic_event")
        events.append(EconomicEvent(**row))
    return events


async def get_economic_event(event_id: str) -> EconomicEvent | None:
    """Get one persisted economic event by ID."""
    row = db_get_economic_event(event_id)
    if row is None:
        return None
    row["tags"] = get_event_tags(event_id, "economic_event")
    return EconomicEvent(**row)


async def get_calendar_provenance(provider_name: str = "Finnhub") -> dict[str, Any]:
    provider = get_provider(provider_name)
    if provider is None:
        return {
            "source": provider_name,
            "provider_version": "unknown",
            "coverage": "US economic calendar",
            "entitlement": "unavailable",
        }
    return {
        "source": provider.name,
        "provider_version": provider.meta["version"],
        "coverage": "US economic calendar",
        "entitlement": "configured-provider" if provider.is_configured else "unavailable",
    }


async def get_economic_event_snapshot(event_id: str, provider_version: str = "finnhub-v1") -> dict[str, Any] | None:
    """Get an immutable event snapshot for backtest reproducibility."""
    snapshot = get_event_snapshot(event_id, provider_version, "economic_event")
    return snapshot["snapshot_data"] if snapshot else None
