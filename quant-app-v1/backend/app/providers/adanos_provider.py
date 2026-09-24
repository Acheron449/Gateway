"""Adanos sentiment provider — structured stock sentiment snapshots.

Adanos aggregates cross-source sentiment (Reddit, X.com, news, Polymarket) into
a single structured payload per symbol. This adapter wraps the optional Adanos
API so Gateway can surface sentiment alongside canonical price data.
"""

from __future__ import annotations

import os
from typing import Any

from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError


ADANOS_BASE = "https://api.adanos.org"
ADANOS_VERSION = "adanos-v1"


class AdanosSentimentProvider(MarketDataProvider):
    """Read-only sentiment provider backed by the optional Adanos API."""

    def __init__(self, api_key: str = "", base_url: str = ADANOS_BASE) -> None:
        self._api_key = api_key.strip() or os.getenv("ADANOS_API_KEY", "").strip()
        self._base_url = base_url.rstrip("/")
        self._client = None

    @property
    def name(self) -> str:
        return "Adanos"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "Adanos",
            "version": ADANOS_VERSION,
            "endpoint": self._base_url,
            "requires_api_key": True,
            "rate_limit_per_min": 60,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def _http(self):
        import httpx
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    async def sentiment(self, symbol: str) -> dict[str, Any] | None:
        """Return a structured sentiment snapshot for a symbol, or None if unavailable."""
        if not self.is_configured or not symbol:
            return None
        try:
            response = await self._http.get(
                f"{self._base_url}/v1/sentiment",
                params={"symbol": symbol.upper()},
                headers=self._headers(),
            )
        except Exception as exc:
            raise ProviderUnavailableError("Adanos sentiment request failed") from exc
        if response.status_code != 200:
            raise ProviderUnavailableError("Adanos sentiment request was rejected")
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError("Adanos sentiment response was malformed") from exc
        if not isinstance(payload, dict):
            raise ProviderUnavailableError("Adanos sentiment response was malformed")
        return payload

    async def quote(self, instrument: str) -> dict[str, Any] | None:
        """Adanos does not provide price quotes."""
        return None

    async def news(self, symbol: str | None = None, limit: int = 5) -> list[Any]:
        """Adanos does not provide raw news; use the sentiment endpoint instead."""
        return []

    async def health_check(self) -> dict[str, Any]:
        result = await super().health_check()
        if not self.is_configured:
            return result
        try:
            response = await self._http.get(
                f"{self._base_url}/v1/health",
                headers=self._headers(),
                timeout=5.0,
            )
            result.update(
                {
                    "status": "healthy" if response.status_code == 200 else "degraded",
                    "latency_ms": round(response.elapsed.total_seconds() * 1000, 2) if response.elapsed else None,
                }
            )
        except Exception:
            result.update({"status": "degraded"})
        return result

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = ["AdanosSentimentProvider"]