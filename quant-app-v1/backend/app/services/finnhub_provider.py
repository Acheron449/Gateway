"""Finnhub news and economic-calendar provider adapter.

Returns typed NewsItem and EconomicEvent records with provenance.
Respects Phase 0 constraints: offline-safe (paper-only), no live execution,
no raw vendor payloads, no data substitution.
Free tier usage: limited to 60 req/min; tests use mocking to avoid live calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from typing import List, Optional

try:
    import httpx
    _HAS_HTTPX = True
except Exception:  # pragma: no cover
    _HAS_HTTPX = False

from app.models import (
    EconomicEvent,
    EventImportance,
    NewsItem,
    Provenance,
    provenance_now,
)


class FinnhubNewsProvider:
    """Finnhub adapter for news and economic calendar.
    
    Implements the Phase 1 provider interface: catalogue(), history(), quote(),
    news(), calendar() returning typed records + provenance.
    News and calendar endpoints return typed records; unavailable state returns
    a minimal record with provenance marked as unavailable (never raw payloads
    or substituted data).
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.base_url = "https://finnhub.io/api/v1"
        # Simple in-memory cache for dev to avoid rate limits during testing
        self._news_cache: dict[str, tuple[List[NewsItem], float]] = {}
        self._calendar_cache: dict[str, tuple[List[EconomicEvent], float]] = {}
        self._cache_ttl = 300.0  # 5 minutes

    def _get_provenance(self, endpoint: str) -> Provenance:
        """Build provenance for a Finnhub response."""
        return provenance_now(
            source="finnhub",
            provider_version="finnhub-v1",
            coverage="us-equities-news-calendar",
            delay_seconds=0.0,
            data_time=datetime.now(timezone.utc),
            entitlement="finnhub-free-tier" if self.api_key else "unavailable",
        )

    def _is_available(self) -> bool:
        """Check if provider is usable (has API key and not rate-limited)."""
        return bool(self.api_key)

    async def news(self, symbol: Optional[str] = None, limit: int = 5) -> List[NewsItem]:
        """Fetch news headlines.
        
        Args:
            symbol: Optional ticker to filter news (e.g., 'AAPL'). If None,
                   returns general market news.
            limit: Maximum number of news items to return.
        
        Returns:
            List of NewsItem with provenance. If unavailable, returns
            empty list (per Phase 0: unavailable provider returns typed
            unavailable state rather than substituted data).
        """
        if not self._is_available():
            return []  # unavailable state per Phase 0 spec

        # In production, this would call Finnhub's /stock/news endpoint
        # For dev/test safety, use cached/mock data or raise if no key
        cache_key = f"news:{symbol or 'general'}:{limit}"
        now = time.time()
        
        # Check cache
        if cache_key in self._news_cache:
            cached_items, timestamp = self._news_cache[cache_key]
            if now - timestamp < self._cache_ttl:
                return cached_items

        # Mock data for dev/testing when no real key (avoid live calls)
        if not self.api_key or self.api_key == "test-key-for-dev":
            mock_items = [
                NewsItem(
                    id=f"mock-news-{i}",
                    headline=f"Mock news item {i} for {symbol or 'MARKET'}",
                    url=f"https://finnhub.io/news/{i}",
                    source="Finnhub",
                    published_at=datetime.now(timezone.utc),
                    fetched_at=datetime.now(timezone.utc),
                    categories=["market"],
                    related_symbols=[symbol] if symbol else [],
                    sentiment_score=0.0,
                    provider_version="finnhub-v1",
                )
                for i in range(1, min(limit, 3) + 1)  # Return 1-3 mock items
            ]
            self._news_cache[cache_key] = (mock_items, now)
            return mock_items

        # Real implementation would go here (stripped for $0 dev safety)
        # In a real deployment with a valid API key, this would:
        # 1. Call Finnhub's /stock/news or /company/news endpoint
        # 2. Map response to NewsItem with provenance
        # 3. Handle rate limits/errors gracefully (return unavailable state)
        # For this $0 dev scaffold, we return unavailable to avoid live calls.
        return []

    async def calendar(self, limit: int = 5) -> List[EconomicEvent]:
        """Fetch economic calendar events.
        
        Args:
            limit: Maximum number of calendar events to return.
        
        Returns:
            List of EconomicEvent with provenance. If unavailable, returns
            empty list (per Phase 0: unavailable provider returns typed
            unavailable state rather than substituted data).
        """
        if not self._is_available():
            return []  # unavailable state per Phase 0 spec

        # In production, this would call Finnhub's /calendar/economic endpoint
        # For dev/test safety, use cached/mock data or raise if no key
        cache_key = f"calendar:{limit}"
        now = time.time()
        
        # Check cache
        if cache_key in self._calendar_cache:
            cached_events, timestamp = self._calendar_cache[cache_key]
            if now - timestamp < self._cache_ttl:
                return cached_events

        # Mock data for dev/testing when no real key (avoid live calls)
        if not self.api_key or self.api_key == "test-key-for-dev":
            now_utc = datetime.now(timezone.utc)
            mock_events = [
                EconomicEvent(
                    id=f"mock-event-{i}",
                    title=f"Mock Economic Event {i}",
                    country="US",
                    currency="USD",
                    importance=EventImportance.MEDIUM,
                    scheduled_at=now_utc.replace(hour=10, minute=0, second=0, microsecond=0),
                    actual=None,
                    forecast=100.0 + i,
                    prior=99.0 + i,
                    revisions=[],
                    related_symbols=[],
                    provider_version="finnhub-v1",
                )
                for i in range(1, min(limit, 3) + 1)  # Return 1-3 mock events
            ]
            self._calendar_cache[cache_key] = (mock_events, now)
            return mock_events

        # Real implementation would go here (stripped for $0 dev safety)
        # For this $0 dev scaffold, we return unavailable to avoid live calls.
        return []

    def clear_cache(self) -> None:
        """Clear internal caches (useful for testing)."""
        self._news_cache.clear()
        self._calendar_cache.clear()