"""AllTick provider — historical K-lines over AllTick's REST API.

Requires an AllTick token (``ALLTICK_API_KEY`` env var or a key saved on the
Providers settings page). The ``httpx`` module is loaded lazily through the
helper declared at the top of this file.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError


def _httpx():
    """Lazy import: load httpx on first use, not at module import time."""
    import httpx

    return httpx


_BASE_URL = "https://quote.alltick.co/quote-stock-b-api"
_MAX_BARS = 500

# Gateway timeframe -> AllTick kline_type
# (1=1m 2=5m 3=15m 4=30m 5=1h 7=4h 8=daily 9=weekly 10=monthly).
_KLINE_TYPE_MAP = {
    "1m": 1,
    "5m": 2,
    "15m": 3,
    "30m": 4,
    "1h": 5,
    "4h": 7,
    "5h": 5,  # resampled to 5h by the gateway after fetching hourly bars
    "1d": 8,
    "1wk": 9,
}


def _to_code(instrument: str) -> str:
    """AllTick uses exchange-suffixed codes (AAPL -> AAPL.US)."""
    symbol = instrument.strip().upper()
    if "." in symbol or "-" in symbol:
        return symbol
    return f"{symbol}.US"


class AllTickProvider(MarketDataProvider):
    """AllTick k-line feed (token required)."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key.strip()

    @property
    def name(self) -> str:
        return "AllTick"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "AllTick",
            "version": "alltick-v1",
            "endpoint": "https://quote.alltick.co",
            "requires_api_key": True,
            "rate_limit_per_min": 6,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def _kline(self, instrument: str, kline_type: int, bars: int) -> list[dict[str, Any]]:
        if not self.is_configured:
            raise ProviderUnavailableError("AllTick API key is not configured")

        query = {
            "trace": uuid.uuid4().hex,
            "data": {
                "code": _to_code(instrument),
                "kline_type": kline_type,
                "kline_timestamp_end": 0,
                "query_kline_num": max(1, min(bars, _MAX_BARS)),
                "adjust_type": 0,
            },
        }
        params = {"token": self._api_key, "query": json.dumps(query, separators=(",", ":"))}

        httpx = _httpx()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{_BASE_URL}/kline", params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError(f"AllTick request failed: {exc or 'network error'}") from exc

        if not isinstance(payload, dict) or payload.get("ret") != 200:
            message = payload.get("msg") if isinstance(payload, dict) else None
            raise ProviderUnavailableError(
                f"AllTick rejected the request: {message or 'unknown error'}",
                status_code=401 if str(message).lower().find("token") >= 0 else None,
            )
        data = payload.get("data")
        rows = data.get("kline_list") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ProviderUnavailableError("AllTick returned no K-line data")

        candles: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                candles.append(
                    {
                        "time": int(float(row.get("timestamp", 0))),
                        "open": float(row.get("open_price", 0)),
                        "high": float(row.get("high_price", 0)),
                        "low": float(row.get("low_price", 0)),
                        "close": float(row.get("close_price", 0)),
                        "volume": float(row.get("volume", 0) or 0),
                    }
                )
            except (TypeError, ValueError):
                continue
        candles = [candle for candle in candles if candle["close"] > 0]
        candles.sort(key=lambda candle: candle["time"])
        if not candles:
            raise ProviderUnavailableError(
                f"AllTick returned no K-line data for {instrument.upper()}"
            )
        return candles

    async def quote(self, instrument: str) -> Optional[dict[str, Any]]:
        """Last price from the latest daily K-line (used by the key test)."""
        candles = await self._kline(instrument, kline_type=8, bars=2)
        last = candles[-1]
        previous = candles[-2] if len(candles) > 1 else None
        change = last["close"] - (previous["close"] if previous else last["open"])
        base = (previous["close"] if previous else last["open"]) or last["close"]
        return {
            "symbol": _to_code(instrument),
            "price": round(last["close"], 4),
            "change": round(change, 4),
            "change_pct": round((change / base * 100.0) if base else 0.0, 2),
            "provider_version": "alltick-v1",
        }

    async def history(
        self,
        instrument: str,
        interval: str = "1d",
        range: str = "1y",
    ) -> Optional[list[dict[str, Any]]]:
        if not self.is_configured:
            return None

        kline_type = _KLINE_TYPE_MAP.get(str(interval).lower(), 8)
        try:
            return await self._kline(instrument, kline_type, _MAX_BARS)
        except ProviderUnavailableError:
            return None
