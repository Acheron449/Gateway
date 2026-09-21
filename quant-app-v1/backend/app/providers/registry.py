"""Provider registry, encrypted key storage, and factory."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings
from app.providers.base import MarketDataProvider, ProviderMeta
from app.providers.finnhub_provider import FinnhubProvider
from app.providers.openbb_provider import OpenBBConfig, OpenBBProvider
from app.providers.openbb_server_provider import OpenBBServerProvider


class TradingViewProvider(MarketDataProvider):
    """Read-only placeholder for a provider that has no Gateway BYOK path."""

    def __init__(self, api_key: str = "", paper_trading: bool = True) -> None:
        self._api_key = api_key
        self._paper_trading = paper_trading

    @property
    def name(self) -> str:
        return "TradingView"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "TradingView",
            "version": "tv-v1",
            "endpoint": "https://data.tradingview.com",
            "requires_api_key": True,
            "rate_limit_per_min": None,
        }

    @property
    def is_configured(self) -> bool:
        return False


_PROVIDER_CLASSES: dict[str, type[MarketDataProvider]] = {
    "Finnhub": FinnhubProvider,
    "TradingView": TradingViewProvider,
    "OpenBB": OpenBBProvider,
    "OpenBB-Server": OpenBBServerProvider,
}

_SETTINGS_DIR = Path(__file__).resolve().parent.parent / "settings"
_SETTINGS_FILE = _SETTINGS_DIR / "provider_keys.json"


def _canonical_name(selected: str) -> str | None:
    wanted = selected.strip().casefold()
    for name in _PROVIDER_CLASSES:
        if name.casefold() == wanted:
            return name
    return None


def _ensure_settings_dir() -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def _load_settings() -> dict[str, str]:
    _ensure_settings_dir()
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        with _SETTINGS_FILE.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_settings(settings: dict[str, str]) -> None:
    _ensure_settings_dir()
    temporary = _SETTINGS_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, _SETTINGS_FILE)
    try:
        _SETTINGS_FILE.chmod(0o600)
    except OSError:
        pass


def _encryption_key() -> bytes | None:
    value = os.getenv("GATEWAY_PROVIDER_KEY", "").strip()
    if not value:
        key_file = os.getenv("GATEWAY_PROVIDER_KEY_FILE", "").strip()
        if not key_file:
            return None
        try:
            value = Path(key_file).read_text(encoding="utf-8").strip()
        except OSError:
            return None
    try:
        Fernet(value.encode("utf-8"))
    except (ValueError, InvalidToken):
        return None
    return value.encode("utf-8")


def _make_fernet_key() -> bytes:
    return Fernet.generate_key()


def _encrypt_key(plain: str, key: bytes) -> str:
    return Fernet(key).encrypt(plain.encode("utf-8")).decode("ascii")


def _decrypt_key(cipher: str, key: bytes) -> str:
    return Fernet(key).decrypt(cipher.encode("ascii")).decode("utf-8")


def _read_stored_api_key(provider: str) -> Optional[str]:
    name = _canonical_name(provider)
    if name is None:
        return None
    settings = _load_settings()
    encrypted = next((value for key, value in settings.items() if key.casefold() == name.casefold()), None)
    if not encrypted:
        return None
    encryption_key = _encryption_key()
    if not encryption_key:
        return None
    try:
        return _decrypt_key(encrypted, encryption_key)
    except Exception:
        return None


def _read_api_key(provider: str) -> Optional[str]:
    stored = _read_stored_api_key(provider)
    if stored:
        return stored
    if _canonical_name(provider) == "Finnhub":
        value = os.getenv("FINNHUB_API_KEY", "").strip()
        return value or None
    return None


def has_stored_key(provider: str) -> bool:
    name = _canonical_name(provider)
    if name is None:
        return False
    return any(key.casefold() == name.casefold() for key in _load_settings())


def _store_api_key(provider: str, key: str) -> None:
    name = _canonical_name(provider)
    if name is None or name != "Finnhub":
        raise ValueError("Only Finnhub supports browser-managed API keys")
    value = key.strip()
    if not value:
        raise ValueError("API key must not be empty")
    encryption_key = _encryption_key()
    if not encryption_key:
        raise RuntimeError("GATEWAY_PROVIDER_KEY or GATEWAY_PROVIDER_KEY_FILE is not set")
    settings = _load_settings()
    settings[name] = _encrypt_key(value, encryption_key)
    _save_settings(settings)


def _delete_api_key(provider: str) -> bool:
    name = _canonical_name(provider)
    if name is None:
        return False
    settings = _load_settings()
    matched = next((key for key in settings if key.casefold() == name.casefold()), None)
    if matched is None:
        return False
    del settings[matched]
    _save_settings(settings)
    return True


def get_provider(
    selected: str,
    api_key: Optional[str] = None,
) -> Optional[MarketDataProvider]:
    name = _canonical_name(selected)
    if name is None:
        return None

    if name == "Finnhub":
        key = api_key if api_key is not None else _read_api_key(name)
        return FinnhubProvider(api_key=key or "")

    if name == "OpenBB":
        if not get_settings().enable_openbb_data:
            return None
        return OpenBBProvider(OpenBBConfig())

    if name == "OpenBB-Server":
        if not get_settings().enable_openbb_server:
            return None
        return OpenBBServerProvider()

    provider_class = _PROVIDER_CLASSES[name]
    return provider_class(api_key=api_key or "")


def list_providers() -> dict[str, ProviderMeta]:
    return {
        "Finnhub": FinnhubProvider("").meta,
        "TradingView": TradingViewProvider("").meta,
        "OpenBB": OpenBBProvider().meta,
        "OpenBB-Server": OpenBBServerProvider().meta,
    }


def register_provider(name: str, cls: type[MarketDataProvider]) -> None:
    if not issubclass(cls, MarketDataProvider):
        raise ValueError(f"{cls} must inherit from MarketDataProvider")
    _PROVIDER_CLASSES[name] = cls


_PROVIDERS = _PROVIDER_CLASSES

__all__ = [
    "FinnhubProvider",
    "TradingViewProvider",
    "MarketDataProvider",
    "ProviderMeta",
    "_PROVIDERS",
    "_PROVIDER_CLASSES",
    "_load_settings",
    "_save_settings",
    "_read_api_key",
    "_read_stored_api_key",
    "_store_api_key",
    "_delete_api_key",
    "_make_fernet_key",
    "_encrypt_key",
    "_decrypt_key",
    "has_stored_key",
    "get_provider",
    "list_providers",
    "register_provider",
]
