"""Provider package for market data adapters."""

from app.providers.base import MarketDataProvider, ProviderMeta, ProviderConfig, ProviderUnavailableError
from app.providers.finnhub_provider import FinnhubProvider
from app.providers.registry import (
    _delete_api_key,
    _read_api_key,
    _read_stored_api_key,
    _store_api_key,
    get_provider,
    has_stored_key,
    list_providers,
    register_provider,
)

__all__ = [
    "MarketDataProvider",
    "ProviderMeta",
    "ProviderConfig",
    "FinnhubProvider",
    "get_provider",
    "list_providers",
    "register_provider",
    "_read_api_key",
    "_read_stored_api_key",
    "_store_api_key",
    "_delete_api_key",
    "ProviderUnavailableError",
    "has_stored_key",
]
