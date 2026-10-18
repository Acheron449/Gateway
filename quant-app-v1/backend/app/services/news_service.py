"""News persistence service for canonical provider records."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.models import NewsItem
from app.providers import get_provider
from app.providers.base import ProviderUnavailableError
from app.services.as_of import normalize_as_of, supports_keyword_argument
from app.services.database import (
    get_news_item as db_get_news_item,
    get_news_items as db_get_news_items,
    get_event_snapshot,
    get_event_tags,
    insert_event_tags,
    insert_news_item,
    store_event_snapshot,
)

# Finnhub's news endpoint is per-symbol, so "general" news fans out across a
# basket of liquid names.
GENERAL_NEWS_SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY", "TSLA", "AMZN"]
_general_fetch_state = {"at": 0.0}
_GENERAL_FETCH_TTL_SECONDS = 60.0


def _news_tags(item: NewsItem) -> list[dict[str, Any]]:
    tags: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for symbol in item.related_symbols:
        key = ("instrument", symbol.upper())
        if key not in seen:
            seen.add(key)
            tags.append({"tag_type": "instrument", "tag_value": symbol.upper(), "confidence": 1.0, "model_version": "gateway-mapping-v1"})
    for category in item.categories:
        key = ("category", str(category))
        if key not in seen:
            seen.add(key)
            tags.append({"tag_type": "category", "tag_value": str(category), "confidence": 1.0, "model_version": "gateway-mapping-v1"})
    return tags


async def fetch_and_store_news(
    provider_name: str = "Finnhub",
    symbol: str | None = None,
    limit: int = 20,
    *,
    as_of: datetime | None = None,
) -> list[NewsItem]:
    """Fetch, tag, snapshot, and persist news from a configured provider."""
    as_of = normalize_as_of(as_of)
    provider = get_provider(provider_name)
    if not provider or not provider.is_configured:
        return []

    if symbol is None:
        # General news: serve recently stored items within a short TTL so
        # repeated requests don't hammer the upstream provider.
        now = time.time()
        if now - _general_fetch_state["at"] < _GENERAL_FETCH_TTL_SECONDS:
            stored = await get_news_items(limit=limit)
            if stored:
                if as_of is None:
                    return stored
                return [
                    item
                    for item in stored
                    if item.published_at is not None
                    and item.published_at.tzinfo is not None
                    and item.published_at.astimezone(timezone.utc) <= as_of
                ]

        merged: dict[str, NewsItem] = {}
        per_symbol = max(3, limit // len(GENERAL_NEWS_SYMBOLS) + 1)
        for sym in GENERAL_NEWS_SYMBOLS:
            try:
                news = provider.news
                kwargs = {"symbol": sym, "limit": per_symbol}
                if as_of is not None and supports_keyword_argument(news, "as_of"):
                    kwargs["as_of"] = as_of
                fetched = await news(**kwargs)
            except ProviderUnavailableError:
                continue
            except Exception:
                continue
            for item in fetched:
                if as_of is None or item.published_at is not None:
                    merged.setdefault(item.id, item)
            if len(merged) >= limit:
                break
        items = list(merged.values())[:limit]
        _general_fetch_state["at"] = time.time()
    else:
        news = provider.news
        kwargs = {"symbol": symbol, "limit": limit}
        if as_of is not None and supports_keyword_argument(news, "as_of"):
            kwargs["as_of"] = as_of
        items = await news(**kwargs)

    if as_of is not None:
        items = [
            item
            for item in items
            if item.published_at is not None
            and item.published_at.tzinfo is not None
            and item.published_at.astimezone(timezone.utc) <= as_of
        ]

    fetched_at = datetime.now(timezone.utc).isoformat()
    stored_items: list[NewsItem] = []
    for item in items:
        item.tags = _news_tags(item)
        # Keep the publisher name (Reuters, Barrons.com, …) when the provider
        # supplied one; fall back to the provider name for consistency.
        if not item.source:
            item.source = provider.name
        item.provider_version = provider.meta["version"]
        item.fetched_at = datetime.fromisoformat(fetched_at)
        item.entitlement = "finnhub-free-tier" if provider.name == "Finnhub" else item.entitlement
        item_dict = item.model_dump(mode="json")
        item_dict["fetched_at"] = fetched_at
        insert_news_item(item_dict)
        store_event_snapshot(item.id, "news", item_dict, provider.meta["version"])
        insert_event_tags(item.id, "news", item.tags)
        stored_items.append(item)
    return stored_items


async def get_news_items(
    since: str | None = None,
    symbols: list[str] | None = None,
    limit: int = 100,
) -> list[NewsItem]:
    """Get persisted news with derived tags."""
    rows = db_get_news_items(since=since, symbols=symbols, limit=limit)
    items: list[NewsItem] = []
    for row in rows:
        row["tags"] = get_event_tags(row["id"], "news")
        items.append(NewsItem(**row))
    return items


async def get_news_item(news_id: str) -> NewsItem | None:
    """Get one persisted news item by ID."""
    row = db_get_news_item(news_id)
    if row is None:
        return None
    row["tags"] = get_event_tags(news_id, "news")
    return NewsItem(**row)


async def get_news_provenance(provider_name: str = "Finnhub") -> dict[str, Any]:
    provider = get_provider(provider_name)
    if provider is None:
        return {
            "source": provider_name,
            "provider_version": "unknown",
            "coverage": "US equities news",
            "entitlement": "unavailable",
        }
    return {
        "source": provider.name,
        "provider_version": provider.meta["version"],
        "coverage": "US equities news",
        "entitlement": "configured-provider" if provider.is_configured else "unavailable",
    }


async def get_news_item_snapshot(news_id: str, provider_version: str = "finnhub-v1") -> dict[str, Any] | None:
    """Get an immutable news snapshot for backtest reproducibility."""
    snapshot = get_event_snapshot(news_id, provider_version, "news")
    return snapshot["snapshot_data"] if snapshot else None
