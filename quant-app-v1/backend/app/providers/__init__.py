"""Provider package for market data adapters.
Lazy imports to avoid circular dependency with service layer.
"""
from __future__ import annotations
from app.providers.base import MarketDataProvider, ProviderMeta, ProviderConfig, ProviderUnavailableError

# Lazy-load provider implementations to break circular imports
# (provider_registry <-> services/provider_registry loop)

def __getattr__(name: str):
    if name == "FinnhubProvider":
        from app.providers.finnhub_provider import FinnhubProvider
        return FinnhubProvider
    if name == "AlpacaProvider":
        from app.providers.alpaca_provider import AlpacaProvider
        return AlpacaProvider
    if name == "OpenBBProvider":
        from app.providers.openbb_provider import OpenBBProvider
        return OpenBBProvider
    if name == "OpenBBServerProvider":
        from app.providers.openbb_server_provider import OpenBBServerProvider
        return OpenBBServerProvider
    if name == "TradingViewProvider":
        from app.providers.registry import TradingViewProvider
        return TradingViewProvider
    # Registry functions — lazy import to avoid registry initialization during module load
    if name == "get_provider":
        from app.providers.registry import get_provider
        return get_provider
    if name == "list_providers":
        from app.providers.registry import list_providers
        return list_providers
    if name == "register_provider":
        from app.providers.registry import register_provider
        return register_provider
    if name == "has_stored_key":
        from app.providers.registry import has_stored_key
        return has_stored_key
    if name == "_read_api_key":
        from app.providers.registry import _read_api_key
        return _read_api_key
    if name == "_store_api_key":
        from app.providers.registry import _store_api_key
        return _store_api_key
    if name == "_delete_api_key":
        from app.providers.registry import _delete_api_key
        return _delete_api_key
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MarketDataProvider",
    "ProviderMeta",
    "ProviderConfig",
    "ProviderUnavailableError",
    "FinnhubProvider",
    "AlpacaProvider",
    "OpenBBProvider",
    "OpenBBServerProvider",
    "TradingViewProvider",
    "get_provider",
    "list_providers",
    "register_provider",
    "has_stored_key",
    "_read_api_key",
    "_store_api_key",
    "_delete_api_key",
]
