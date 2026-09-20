"""News service for fetching and storing news items from providers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.models import NewsItem
from app.providers import get_provider
from app.services.database import (
    get_news_items as db_get_news_items,
    insert_news_item,
    get_news_item as db_get_news_item,
)


async def fetch_and_store_news(
    provider_name: str = "Finnhub",
    symbol: Optional[str] = None,
    limit: int = 20,
) -> List[NewsItem]:
    """Fetch news from provider and store in database."""
    provider = get_provider(provider_name)
    if not provider or not provider.is_configured:
        return []

    try:
        items = await provider.news(symbol=symbol, limit=limit)
    except Exception:
        return []

    stored_items = []
    now = datetime.now(timezone.utc).isoformat()
    for item in items:
        item_dict = item.model_dump(mode="json")
        item_dict.update({
            "source": provider_name,
            "fetched_at": now,
        })
        insert_news_item(item_dict)
        stored_items.append(item)

    return stored_items


async def get_news_items(
    since: str | None = None,
    symbols: List[str] | None = None,
    limit: int = 100,
) -> List[NewsItem]:
    """Get news items from database with filters."""
    items_data = db_get_news_items(
        since=since,
        symbols=symbols,
        limit=limit,
    )
    return [NewsItem(**i) for i in items_data]


async def get_news_item(news_id: str) -> NewsItem | None:
    """Get a single news item by ID."""
    item_data = db_get_news_item(news_id)
    if not item_data:
        return None
    return NewsItem(**item_data)


async def get_news_provenance() -> Dict[str, Any]:
    """Get provenance info for the news data source."""
    return {
        "source": "Finnhub",
        "provider_version": "finnhub-v1",
        "coverage": "US equities news",
        "entitlement": "configured-provider",
    }


async def get_news_item_snapshot(news_id: str) -> Dict[str, Any] | None:
    """Get a snapshot of a news item for backtest reproducibility."""
    from app.services.database import get_event_snapshot
    snapshot = get_event_snapshot(news_id, "finnhub-v1")
    if not snapshot:
        return None
    return snapshot["snapshot_data"]