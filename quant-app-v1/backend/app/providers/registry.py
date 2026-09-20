"""Provider registry and factory for market data providers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet

from app.providers.base import MarketDataProvider, ProviderMeta
from app.providers.finnhub_provider import FinnhubProvider


_PROVIDER_CLASSES: Dict[str, type] = {
    "Finnhub": FinnhubProvider,
}


def _make_fernet_key() -> bytes:
    """Generate a new 256-bit key for encrypting API keys at rest."""
    return Fernet.generate_key()


def _encrypt_key(plain: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(plain.encode()).decode()


def _decrypt_key(cipher: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(cipher.encode()).decode()


# ---------------------------------------------------------------------------
# Provider registry + persistence (encrypted JSON file)
# ---------------------------------------------------------------------------

_SETTINGS_DIR = Path(__file__).parent.parent / "settings"
_SETTINGS_FILE = _SETTINGS_DIR / "provider_keys.json"


def _ensure_settings_dir() -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def _load_settings() -> Dict[str, str]:
    """Return dict {provider_name: encrypted_api_key} from disk."""
    _ensure_settings_dir()
    if not _SETTINGS_FILE.exists():
        return {}
    try:
        with open(_SETTINGS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_settings(settings: Dict[str, str]) -> None:
    _ensure_settings_dir()
    with open(_SETTINGS_FILE, "w") as f:
        json.dump(settings, f)


# ---------------------------------------------------------------------------
# Endpoint-level helpers – the ``/settings/providers`` route will call
# these so the UI can read / write keys without ever hitting raw code.
# ---------------------------------------------------------------------------

def _read_api_key(provider: str) -> Optional[str]:
    """Decrypt and return the stored key, or None if absent / error."""
    settings = _load_settings()
    enc = settings.get(provider)
    if not enc:
        return None
    try:
        env_key = os.getenv("GATEWAY_PROVIDER_KEY", "")
        if not env_key:
            return None
        return _decrypt_key(enc, env_key.encode())
    except Exception:
        return None


def _store_api_key(provider: str, key: str) -> None:
    """Encrypt and persist the key for *provider*."""
    settings = _load_settings()
    env_key = os.getenv("GATEWAY_PROVIDER_KEY", "")
    if not env_key:
        raise RuntimeError("GATEWAY_PROVIDER_KEY not set in environment")
    settings[provider] = _encrypt_key(key, env_key.encode())
    _save_settings(settings)


# ---------------------------------------------------------------------------
# Provider factory – the single place the backend asks for a provider
# instance keyed by the user's selection in the UI.
# ---------------------------------------------------------------------------

def get_provider(selected: str, api_key: Optional[str] = None) -> Optional[MarketDataProvider]:
    """Return an instantiated provider or ``None`` if not configured."""
    provider_class = _PROVIDER_CLASSES.get(selected)
    if not provider_class:
        return None
    # If an explicit key was passed (e.g. from a one-off test), use it;
    # otherwise read from the encrypted store.
    if api_key is None:
        api_key = _read_api_key(selected)
    try:
        return provider_class(api_key=api_key)
    except Exception:
        return None


def list_providers() -> Dict[str, ProviderMeta]:
    """Return metadata for all registered providers."""
    return {name: cls("", paper_trading=True).meta for name, cls in _PROVIDER_CLASSES.items()}


def register_provider(name: str, cls: type) -> None:
    """Register a new provider class."""
    if not issubclass(cls, MarketDataProvider):
        raise ValueError(f"{cls} must inherit from MarketDataProvider")
    _PROVIDER_CLASSES[name] = cls