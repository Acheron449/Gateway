from __future__ import annotations

from typing import Any


async def fetch_latest_headlines(ticker: str, limit: int = 5) -> list[dict[str, Any]]:
    """Return no records when no configured provider is available."""
    del ticker, limit
    return []


async def fetch_forex_factory_news(limit: int = 10) -> list[dict[str, Any]]:
    """Return no records; Gateway does not scrape or synthesize news."""
    del limit
    return []
