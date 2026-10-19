"""CCXT market-data adapter — keyless exchange data for crypto instruments.

CCXT is Gateway's **backup** market-data provider: when yfinance fails (or the
user explicitly switches the chart's provider to CCXT), crypto pairs are still
served from a public exchange REST API.  It cannot cover equities — a stock
symbol raises ``ProviderUnavailableError`` so the caller can fall back to
yfinance as before.

Design notes:
- The ``ccxt`` module is imported lazily (same pattern as ``yahoo_provider``)
  so booting the API never pays for ccxt's startup cost.
- No API key: public endpoints of the exchange are enough for OHLCV + tickers.
- The default exchange is Kraken (US-friendly, no key); override with
  ``GATEWAY_CCXT_EXCHANGE`` (any ccxt exchange id, e.g. ``binance``).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Optional

from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError
from app.services.as_of import filter_timestamped_rows, normalize_as_of

DEFAULT_EXCHANGE_ID = "kraken"
CCXT_VERSION = "ccxt-v1"

# Gateway timeframe -> ccxt/kraken timeframe.  ``5h`` has no exchange
# equivalent, so it maps to 4h (the chart's resampler refines it upstream).
_TF_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "5h": "4h",
    "1d": "1d",
    "1wk": "1w",
}

# How far back each yfinance-style ``range`` reaches (milliseconds before now).
_RANGE_MS = {
    "1d": 1,
    "5d": 5,
    "1mo": 31,
    "3mo": 92,
    "6mo": 183,
    "1y": 366,
    "2y": 732,
    "5y": 1830,
}


def _ccxt():
    """Lazy import: load ccxt on first use, not at module import time."""
    import ccxt

    return ccxt


def to_exchange_symbol(instrument: str) -> str:
    """Map a Gateway symbol onto a ccxt market id.

    ``BTC-USD`` / ``BTCUSDT`` / ``BTC`` -> ``BTC/USD`` (Kraken-style);
    anything non-crypto (e.g. ``AAPL``) raises so callers fall back to
    yfinance instead of guessing.
    """
    raw = (instrument or "").strip().upper()
    if not raw:
        raise ProviderUnavailableError("Empty symbol for CCXT")
    if "/" in raw:
        base, _, quote = raw.partition("/")
        return f"{base}/{quote}"

    # Dash form first: BTC-USD / BTC-USDT (splitting before suffix-stripping
    # so "BTC-USD" doesn't get mangled into "BTC-/USD").
    if "-" in raw:
        base, _, quote = raw.partition("-")
        if base and quote:
            return f"{base}/{quote}"

    # Concatenated quote suffix: BTCUSDT, BTCEUR, ...
    for quote in ("USDT", "USDC", "USD", "EUR", "BTC", "ETH"):
        if raw.endswith(quote) and len(raw) > len(quote):
            return f"{raw[: -len(quote)]}/{quote}"

    # Bare base (BTC, ETH): quote with USD, the default for Gateway tickers.
    if raw.isalpha() and len(raw) <= 6:
        return f"{raw}/USD"

    raise ProviderUnavailableError(
        f"CCXT only covers crypto pairs; '{instrument}' is not a crypto symbol"
    )


def _exchange():
    """Build (and cache) the configured ccxt exchange instance."""
    exchange_id = os.getenv("GATEWAY_CCXT_EXCHANGE", DEFAULT_EXCHANGE_ID).strip() or DEFAULT_EXCHANGE_ID
    ccxt = _ccxt()
    factory = getattr(ccxt, exchange_id, None)
    if factory is None:
        raise ProviderUnavailableError(f"Unknown ccxt exchange '{exchange_id}'")
    return factory({"enableRateLimit": True})


class CCXTProvider(MarketDataProvider):
    """Keyless exchange OHLCV/quotes via ccxt (crypto only)."""

    def __init__(self, api_key: str = "", paper_trading: bool = True) -> None:
        # Public endpoints need no credentials; api_key satisfies the uniform
        # registry constructor signature only.
        self._api_key = api_key
        self._paper_trading = paper_trading

    @property
    def name(self) -> str:
        return "CCXT"

    @property
    def meta(self) -> ProviderMeta:
        exchange_id = os.getenv("GATEWAY_CCXT_EXCHANGE", DEFAULT_EXCHANGE_ID).strip() or DEFAULT_EXCHANGE_ID
        return {
            "name": "CCXT",
            "version": CCXT_VERSION,
            "endpoint": f"ccxt://{exchange_id}",
            "requires_api_key": False,
            "rate_limit_per_min": 60,
        }

    @property
    def is_configured(self) -> bool:
        # "Configured" == the dependency is installed and importable.
        try:
            _ccxt()
            return True
        except Exception:
            return False

    async def history(
        self,
        instrument: str,
        interval: str = "1d",
        range: str = "1y",
        *,
        as_of: datetime | None = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Fetch historical OHLCV bars from the configured exchange."""
        symbol = to_exchange_symbol(instrument)  # raises for non-crypto
        timeframe = _TF_MAP.get((interval or "1d").lower(), "1d")
        days = _RANGE_MS.get((range or "1y").lower(), 366)
        cutoff = normalize_as_of(as_of)
        end = cutoff or datetime.now(timezone.utc)
        since = int((end.timestamp() - days * 86400) * 1000)

        def _fetch() -> list[dict[str, Any]]:
            try:
                raw = _exchange().fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
            except ProviderUnavailableError:
                raise
            except Exception as exc:
                raise ProviderUnavailableError(f"ccxt history request failed: {exc}") from exc
            candles: list[dict[str, Any]] = []
            for row in raw or []:
                if not isinstance(row, (list, tuple)) or len(row) < 6:
                    continue
                ts, open_, high, low, close, volume = row[:6]
                if not close or close <= 0:
                    continue
                candles.append(
                    {
                        "time": int(ts) // 1000,  # ccxt uses ms epochs
                        "open": float(open_),
                        "high": float(high),
                        "low": float(low),
                        "close": float(close),
                        "volume": float(volume or 0),
                    }
                )
            candles.sort(key=lambda c: c["time"])
            return filter_timestamped_rows(candles, as_of=as_of)

        return await asyncio.to_thread(_fetch)

    async def quote(self, instrument: str) -> Optional[dict[str, Any]]:
        """Last-price snapshot from the exchange ticker endpoint."""
        symbol = to_exchange_symbol(instrument)

        def _fetch() -> dict[str, Any] | None:
            try:
                ticker = _exchange().fetch_ticker(symbol)
            except ProviderUnavailableError:
                raise
            except Exception as exc:
                raise ProviderUnavailableError(f"ccxt quote request failed: {exc}") from exc
            price = ticker.get("last")
            if not price:
                return None
            # Exchanges report change vs the 24h open; fall back to the
            # percentage field when the open is missing.
            open_ = ticker.get("open")
            change = (float(price) - float(open_)) if open_ else None
            if change is None and ticker.get("percentage") is not None:
                change = float(price) * float(ticker["percentage"]) / 100.0
            change = change or 0.0
            change_pct = float(ticker.get("percentage") or 0.0)
            return {
                "symbol": instrument.upper(),
                "price": round(float(price), 4),
                "change": round(change, 4),
                "change_pct": round(change_pct, 2),
                "provider_version": CCXT_VERSION,
            }

        return await asyncio.to_thread(_fetch)
