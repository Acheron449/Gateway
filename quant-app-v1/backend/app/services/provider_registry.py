"""Provider abstraction layer for market data and news sources.

Phase 1 — supports multiple data providers with BYOK (Bring Your Own Key)
configuration. Primary: Finnhub. Secondary: TradingView (optional).

Each provider returns normalized ``NewsItem`` / ``EconomicEvent`` records
with provenance.  Unavailable or misconfigured provider returns empty
list rather than substituting data (Phase 0 contract).
"""

from __future__ import annotations

import abc
import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from app.models import EconomicEvent, EventImportance, NewsItem, Provenance

# ---------------------------------------------------------------------------
# Typed request / response shapes used across providers and the UI
# ---------------------------------------------------------------------------

class ProviderMeta(TypedDict):
    name: str
    version: str
    endpoint: str
    requires_api_key: bool
    rate_limit_per_min: Optional[int]


class ProviderConfig(TypedDict, total=False):
    api_key: str  # encrypted at rest
    # provider‑specific flags
    paper_trading: bool
    # any extra keys the concrete provider may need
    extra: dict[str, Any]


# ---------------------------------------------------------------------------
# Provider protocol — every concrete provider must honour this interface
# ---------------------------------------------------------------------------

class MarketDataProvider(abc.ABC):
    """Interface all data providers must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @property
    @abc.abstractmethod
    def meta(self) -> ProviderMeta: ...

    @property
    @abc.abstractmethod
    def is_configured(self) -> bool: ...

    # --- News ---

    async def news(
        self, symbol: Optional[str] = None, limit: int = 5
    ) -> List[NewsItem]:
        """Fetch headlines; return [] if unavailable / key missing."""

    async def calendar(self, limit: int = 5) -> List[EconomicEvent]:
        """Fetch scheduled economic events; return [] if unavailable."""

    # --- Quote / history (optional, used mainly for order routing) ---

    async def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        return None

    async def history(
        self, symbol: str, interval: str = "1d", range: str = "1y"
    ) -> Optional[List[Dict[str, Any]]]:
        return None

# ---------------------------------------------------------------------------
# Concrete: Finnhub provider — production implementation
# ---------------------------------------------------------------------------

FINNHUB_BASE = "https://finnhub.io/api/v1"
FINNHUB_NEWS_ENDPOINT = "/stock/news"
FINNHUB_CALENDAR_ENDPOINT = "/calendar/economic"
FINNHUB_QUOTE_ENDPOINT = "/quote"

_FINNHUB_RATE_LIMIT = 60  # free tier


class FinnhubProvider(MarketDataProvider):
    """Finnhub-backed provider — free tier 60 req/min, US equities + calendar."""

    def __init__(self, api_key: str, paper_trading: bool = True):
        self._api_key = api_key
        self._paper_trading = paper_trading
        self._client = None  # lazy httpx.AsyncClient

    @property
    def name(self) -> str:
        return "Finnhub"

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            name="Finnhub",
            version="finnhub-v1",
            endpoint=FINNHUB_BASE,
            requires_api_key=True,
            rate_limit_per_min=_FINNHUB_RATE_LIMIT,
        )

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    # ------------------------------------------------------------------
    # Private httpx client (lazy, reused)
    # ------------------------------------------------------------------

    @property
    def _http(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def news(self, symbol: Optional[str] = None, limit: int = 5) -> List[NewsItem]:
        if not self.is_configured:
            return []

        # Build the Finnhub request - pass API key in header, not URL
        symbol_param = symbol or ""
        url = f"{FINNHUB_BASE}{FINNHUB_NEWS_ENDPOINT}?symbol={symbol_param}&limit={limit}"
        headers = {"X-Finnhub-Token": self._api_key} if self._api_key else {}

        try:
            resp = await self._http.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            data = resp.json()

            items: List[NewsItem] = []
            for article in data.get("news", [])[:limit]:
                # Finnhub may omit some fields; use .get with defaults
                items.append(
                    NewsItem(
                        id=article.get("id", hashlib.md5(article.get("url", "").encode()).hexdigest()[:8]),
                        headline=article.get("headline", ""),
                        url=article.get("url"),
                        source=article.get("source", "Finnhub"),
                        published_at=datetime.fromtimestamp(
                            article.get("datetime", int(time.time())), tz=timezone.utc
                        ),
                        fetched_at=datetime.now(timezone.utc),
                        categories=article.get("categories", []),
                        related_symbols=article.get("related_symbol", []),
                        sentiment_score=float(article.get("sentiment", 0.0)),
                        provider_version="finnhub-v1",
                    )
                )
            return items

        except Exception:
            return []

    async def calendar(self, limit: int = 5) -> List[EconomicEvent]:
        if not self.is_configured:
            return []

        url = f"{FINNHUB_BASE}{FINNHUB_CALENDAR_ENDPOINT}?limit={limit}"
        headers = {"X-Finnhub-Token": self._api_key} if self._api_key else {}

        try:
            resp = await self._http.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            data = resp.json()

            events: List[EconomicEvent] = []
            for ev in data.get("economic", [])[:limit]:
                imp_map = {"low": EventImportance.LOW,
                           "medium": EventImportance.MEDIUM,
                           "high": EventImportance.HIGH}
                importance = imp_map.get(ev.get("importance", "medium"), EventImportance.MEDIUM)

                events.append(
                    EconomicEvent(
                        id=ev.get("event", hashlib.md5(ev.get("title", "").encode()).hexdigest()[:8]),
                        title=ev.get("title", ""),
                        country=ev.get("country", "US"),
                        currency=ev.get("currency", "USD"),
                        importance=importance,
                        scheduled_at=datetime.fromtimestamp(
                            ev.get("timestamp", int(time.time())), tz=timezone.utc
                        ),
                        actual=float(ev.get("actual", 0.0)) if ev.get("actual") is not None else None,
                        forecast=float(ev.get("forecast", 0.0)) if ev.get("forecast") is not None else None,
                        prior=float(ev.get("prior", 0.0)) if ev.get("prior") is not None else None,
                        revisions=ev.get("revisions", []),
                        related_symbols=ev.get("related", []),
                        provider_version="finnhub-v1",
                    )
                )
            return events

        except Exception:
            return []

    # ------------------------------------------------------------------
    # Clean‑up
    # ------------------------------------------------------------------

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# ---------------------------------------------------------------------------
# Scaffold: TradingViewProvider — minimal read‑only stub
# ---------------------------------------------------------------------------

_TRADINGVIEW_KEY_REQ = True  # TradingView real‑time needs a paid key / subscription

class TradingViewProvider(MarketDataProvider):
    """Scaffold TradingView provider — currently read‑only, no BYOK support in free tier.

    The TradingView data feed is primarily a charting widget subscription;
    a full API key–based access is paid.  This class exists so the UI
    dropdown can always be populated and the code path is type‑safe, but
    calls will surface ``is_configured == False`` and return [].
    """

    def __init__(self, api_key: str = "", paper_trading: bool = True):
        self._api_key = api_key
        self._paper_trading = paper_trading

    @property
    def name(self) -> str:
        return "TradingView"

    @property
    def meta(self) -> ProviderMeta:
        return ProviderMeta(
            name="TradingView",
            version="tv-v1",
            endpoint="https://data.tradingview.com",
            requires_api_key=_TRADINGVIEW_KEY_REQ,
            rate_limit_per_min=None,  # subscription‑dependent
        )

    @property
    def is_configured(self) -> bool:
        # No BYOK for TV in this scaffold; always False so the UI can
        # display a "subscribe / contact sales" call‑to‑action.
        return False

    async def news(self, symbol: Optional[str] = None, limit: int = 5) -> List[NewsItem]:
        return []

    async def calendar(self, limit: int = 5) -> List[EconomicEvent]:
        return []

    async def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        return None

    async def history(self, symbol: str, interval: str = "1d", range: str = "1y") -> Optional[List[Dict[str, Any]]]:
        return None

# ---------------------------------------------------------------------------
# Settings / key‑storage helpers (Fernet symmetric encryption)
# ---------------------------------------------------------------------------

from cryptography.fernet import Fernet  # standard‑library‑compatible; pip‑installed

def _make_fernet_key() -> bytes:
    """Generate a new 256‑bit key for encrypting API keys at rest."""
    return Fernet.generate_key()

def _encrypt_key(plain: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(plain.encode()).decode()

def _decrypt_key(cipher: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(cipher.encode()).decode()

# ---------------------------------------------------------------------------
# Provider registry + persistence (very small in‑memory + encrypted‑JSON file)
# ---------------------------------------------------------------------------

import json
import os
from pathlib import Path

_SETTINGS_DIR = Path(__import__("pathlib").Path(__file__).parent.parent / "settings")
_SETTINGS_FILE = _SETTINGS_DIR / "provider_keys.json"

def _ensure_settings_dir() -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

def _load_settings() -> Dict[str, str]:
    """Return dict  {provider_name: encrypted_api_key}  from disk."""
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
# Endpoint‑level helpers – the ``/settings/providers`` route will call
# these so the UI can read / write keys without ever hitting raw code.
# ---------------------------------------------------------------------------

def _read_api_key(provider: str) -> Optional[str]:
    """Decrypt and return the stored key, or None if absent / error."""
    settings = _load_settings()
    enc = settings.get(provider)
    if not enc:
        return None
    try:
        # The Fernet key itself is stored in the environment variable
        # GATEWAY_PROVIDER_KEY – rotate it rotate‑rarely.
        env_key = os.getenv("GATEWAY_PROVIDER_KEY", "")
        if not env_key:
            return None
        return _decrypt_key(enc, env_key.encode())
    except Exception:
        return None

def _store_api_key(provider: str, key: str) -> None:
    """Encrypt and persist the key for *provider*."""
    settings = _load_settings()
    settings[provider] = _encrypt_key(key, os.getenv("GATEWAY_PROVIDER_KEY", "").encode())
    _save_settings(settings)

# ---------------------------------------------------------------------------
# Provider factory – the single place the backend asks for a provider
# instance keyed by the user's selection in the UI.
# ---------------------------------------------------------------------------

_PROVIDERS: Dict[str, MarketDataProvider] = {
    "Finnhub": FinnhubProvider,
    "TradingView": TradingViewProvider,
}

def get_provider(selected: str, api_key: Optional[str] = None) -> Optional[MarketDataProvider]:
    """Return an instantiated provider or ``None`` if not configured."""
    provider_class = _PROVIDERS.get(selected)
    if not provider_class:
        return None
    # If an explicit key was passed (e.g. from a one‑off test), use it;
    # otherwise read from the encrypted store.
    if api_key is None:
        api_key = _read_api_key(selected)
    try:
        return provider_class(api_key=api_key)
    except Exception:
        return None