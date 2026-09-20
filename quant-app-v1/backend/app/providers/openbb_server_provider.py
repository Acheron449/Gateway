"""OpenBB Server Provider — connects to standalone openbb-api server.

Phase 6 — Slice 6.4 (optional): OpenBB-API Server Provider
Feature-gated via ENABLE_OPENBB_SERVER (default: false).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.models import Candle, NewsItem, EconomicEvent, EventImportance, Provenance
from app.services.provider_registry import MarketDataProvider, ProviderMeta

logger = logging.getLogger(__name__)


class OpenBBServerProvider(MarketDataProvider):
    """OpenBB server provider connecting to standalone openbb-api (port 6900).

    Requires ENABLE_OPENBB_SERVER=true and openbb-api container running.
    """

    def __init__(self, base_url: str = "http://localhost:6900", timeout: float = 15.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def name(self) -> str:
        return "OpenBB-Server"

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            name="OpenBB-Server",
            version="openbb-api-v1",
            endpoint=self._base_url,
            requires_api_key=False,
            rate_limit_per_min=120,
        )

    @property
    def is_configured(self) -> bool:
        settings = get_settings()
        return settings.enable_openbb_server

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _request(self, method: str, path: str, params: Optional[Dict] = None) -> Any:
        url = f"{self._base_url}{path}"
        try:
            resp = await self._http.request(method, url, params=params)
            if resp.status_code != 200:
                logger.error(f"OpenBB server error {resp.status_code}: {resp.text}")
                return None
            return resp.json()
        except Exception as e:
            logger.error(f"OpenBB server request failed: {e}")
            return None

    async def history(
        self, symbol: str, interval: str = "1d", range: str = "1y"
    ) -> Optional[List[Dict[str, Any]]]:
        """Fetch historical OHLCV data from OpenBB server."""
        if not self.is_configured:
            return None

        # Map interval/period to OpenBB API format
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "period": range,
        }

        data = await self._request("GET", "/api/v1/equity/historical", params)
        if data is None:
            return None

        # Transform server response to Gateway format
        candles = []
        for row in data:
            candles.append({
                "time": row.get("timestamp"),
                "open": row.get("open"),
                "high": row.get("high"),
                "low": row.get("low"),
                "close": row.get("close"),
                "volume": row.get("volume"),
                "provenance": {
                    "source": "openbb-server",
                    "provider_version": "openbb-api-v1",
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "coverage": "US equities / daily",
                    "delay_seconds": 86400,
                    "entitlement": "public",
                }
            })
        return candles

    async def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch real-time quote from OpenBB server."""
        if not self.is_configured:
            return None

        data = await self._request("GET", f"/api/v1/equity/quote", {"symbol": symbol.upper()})
        if data is None:
            return None

        return {
            "symbol": symbol.upper(),
            "last_price": data.get("last_price"),
            "bid": data.get("bid"),
            "ask": data.get("ask"),
            "change": data.get("change"),
            "change_pct": data.get("change_pct"),
            "provenance": {
                "source": "openbb-server",
                "provider_version": "openbb-api-v1",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "coverage": "US equities / real-time",
                "delay_seconds": 1,
                "entitlement": "public",
            }
        }

    async def news(self, symbol: Optional[str] = None, limit: int = 5) -> List[NewsItem]:
        """Fetch news from OpenBB server."""
        if not self.is_configured:
            return []

        params = {"limit": limit}
        if symbol:
            params["symbol"] = symbol

        data = await self._request("GET", "/api/v1/news", params)
        if data is None:
            return []

        items = []
        for item in data:
            items.append(NewsItem(
                id=item.get("id", str(hash(item.get("url", "")))[:8]),
                headline=item.get("title", ""),
                url=item.get("url"),
                source=item.get("source", "OpenBB"),
                published_at=pd.to_datetime(item.get("date", datetime.now())),
                fetched_at=datetime.now(timezone.utc),
                categories=item.get("tags", []),
                related_symbols=item.get("symbols", [symbol] if symbol else []),
                sentiment_score=float(item.get("sentiment", 0.0)),
                provider_version="openbb-api-v1",
            ))
        return items

    async def calendar(self, limit: int = 5) -> List[EconomicEvent]:
        """Fetch economic calendar from OpenBB server."""
        if not self.is_configured:
            return []

        data = await self._request("GET", "/api/v1/economy/calendar", {"limit": limit})
        if data is None:
            return []

        events = []
        for ev in data:
            imp_map = {"low": EventImportance.LOW, "medium": EventImportance.MEDIUM, "high": EventImportance.HIGH}
            importance = imp_map.get(str(ev.get("importance", "medium")).lower(), EventImportance.MEDIUM)

            events.append(EconomicEvent(
                id=ev.get("event", str(hash(ev.get("title", "")))[:8]),
                title=ev.get("title", ""),
                country=ev.get("country", "US"),
                currency=ev.get("currency", "USD"),
                importance=importance,
                scheduled_at=pd.to_datetime(ev.get("date", datetime.now())),
                actual=float(ev.get("actual", 0.0)) if ev.get("actual") is not None else None,
                forecast=float(ev.get("forecast", 0.0)) if ev.get("forecast") is not None else None,
                prior=float(ev.get("previous", 0.0)) if ev.get("previous") is not None else None,
                revisions=ev.get("revisions", []),
                related_symbols=ev.get("related_symbols", []),
                provider_version="openbb-api-v1",
            ))
        return events

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# Add missing imports at the top
from datetime import datetime, timezone
import pandas as pd