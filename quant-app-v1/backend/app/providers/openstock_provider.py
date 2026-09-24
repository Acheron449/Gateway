"""OpenStock symbol lookup provider — wraps Finnhub symbol search with provenance.

OpenStock uses Finnhub's /stock/symbol endpoint for fast symbol search across
30+ international exchanges. This adapter normalises those results into Gateway's
typed Instrument records so the catalogue can be expanded without hard-coding.
"""

from __future__ import annotations

from typing import Any

from app.models import Instrument, Provenance, provenance_now
from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError


OPENSTOCK_BASE = "https://finnhub.io/api/v1"
OPENSTOCK_VERSION = "openstock-v1"


class OpenStockSymbolProvider(MarketDataProvider):
    """Symbol lookup backed by Finnhub's /stock/symbol endpoint (OpenStock's source)."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key.strip()

    @property
    def name(self) -> str:
        return "OpenStock"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "OpenStock",
            "version": OPENSTOCK_VERSION,
            "endpoint": OPENSTOCK_BASE,
            "requires_api_key": True,
            "rate_limit_per_min": 60,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def _http(self):
        import httpx
        if not hasattr(self, "_client") or self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {"X-Finnhub-Token": self._api_key} if self._api_key else {}

    async def catalogue(self) -> list[str]:
        """Return available exchange codes (subset of Finnhub coverage)."""
        return ["US", "LSE", "TSX", "NSE", "BSE", "ETR", "FWB", "PAR", "AMS"]

    async def search(self, query: str, *, exchange: str = "US", limit: int = 20) -> list[Instrument]:
        """Search symbols via Finnhub /stock/symbol and normalise into Instrument records."""
        if not self.is_configured or not query or limit <= 0:
            return []

        try:
            response = await self._http.get(
                f"{OPENSTOCK_BASE}/stock/symbol",
                params={"exchange": exchange, "query": query, "limit": limit},
                headers=self._headers(),
            )
        except Exception as exc:
            raise ProviderUnavailableError("OpenStock symbol search request failed") from exc

        if response.status_code != 200:
            raise ProviderUnavailableError("OpenStock symbol search was rejected")

        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError("OpenStock symbol search response was malformed") from exc

        results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(results, list):
            raise ProviderUnavailableError("OpenStock symbol search response was malformed")

        provenance = provenance_now(
            source="openstock",
            provider_version=OPENSTOCK_VERSION,
            coverage=f"symbol-lookup/{exchange}",
            delay_seconds=0,
        )

        instruments: list[Instrument] = []
        for record in results[:limit]:
            if not isinstance(record, dict):
                continue
            symbol = str(record.get("symbol", "")).strip().upper()
            if not symbol or len(symbol) > 12:
                continue
            try:
                instruments.append(
                    Instrument(
                        symbol=symbol,
                        name=str(record.get("description") or symbol),
                        exchange=str(record.get("exchange") or exchange),
                        currency=str(record.get("currency") or "USD"),
                        instrument_type=str(record.get("type") or "common_stock"),
                        provenance=provenance,
                    )
                )
            except Exception:
                continue
        return instruments

    async def quote(self, instrument: str) -> dict[str, Any] | None:
        """Delegate quote lookup to the underlying Finnhub provider."""
        from app.providers.finnhub_provider import FinnhubProvider
        finn = FinnhubProvider(api_key=self._api_key)
        return await finn.quote(instrument)

    async def health_check(self) -> dict[str, Any]:
        result = await super().health_check()
        if not self.is_configured:
            return result
        try:
            response = await self._http.get(
                f"{OPENSTOCK_BASE}/stock/symbol",
                params={"exchange": "US", "query": "AAPL", "limit": 1},
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
        client = getattr(self, "_client", None)
        if client is not None:
            await client.aclose()
            self._client = None


__all__ = ["OpenStockSymbolProvider"]