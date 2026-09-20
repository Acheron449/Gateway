"""Canonical provider contracts for Gateway data adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, TypedDict


class ProviderMeta(TypedDict):
    name: str
    version: str
    endpoint: str
    requires_api_key: bool
    rate_limit_per_min: int | None


class ProviderConfig(TypedDict, total=False):
    api_key: str
    paper_trading: bool
    extra: dict[str, Any]


class MarketDataProvider(ABC):
    """Base interface for read-only market-data providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider display name."""

    @property
    @abstractmethod
    def meta(self) -> ProviderMeta:
        """Return non-secret provider metadata."""

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return whether the provider can make requests."""

    async def catalogue(self) -> list[str]:
        return []

    async def history(
        self,
        instrument: str,
        interval: str = "1d",
        range: str = "1y",
    ) -> list[dict[str, Any]] | None:
        return None

    async def quote(self, instrument: str) -> dict[str, Any] | None:
        return None

    async def news(
        self,
        symbol: str | None = None,
        limit: int = 5,
    ) -> list[Any]:
        return []

    async def calendar(self, limit: int = 5) -> list[Any]:
        return []

    async def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "status": "healthy" if self.is_configured else "unavailable",
            "configured": self.is_configured,
        }

    async def close(self) -> None:
        return None


Provider = MarketDataProvider

__all__ = [
    "MarketDataProvider",
    "Provider",
    "ProviderMeta",
    "ProviderConfig",
]
