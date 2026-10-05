"""London Strategic Edge (LSE) vault adapter for history and quotes.

Compatibility with https://londonstrategicedge.com/data#api — the free LSE
databank (133B ticks / 118K datasets) served over REST:

    GET https://api.londonstrategicedge.com/vault/<path>
    Header: x-api-key: <free key from londonstrategicedge.com/data>

Interactive reads are plain JSON row lists (``/vault/candles`` for OHLCV at
fourteen resolutions, ``/vault/series`` for macro series). Bulk Parquet export
jobs are out of scope here — charts only need the interactive endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError

LSE_VAULT_URL = "https://api.londonstrategicedge.com/vault"
LSE_VERSION = "lse-vault-v1"
LSE_RATE_LIMIT = 120  # free tier shares one allowance between REST and stream

# Gateway / yfinance interval -> vault timeframe (vault resolutions: 1s, 5s,
# 15s, 30s, 1m, 3m, 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1mo).
_INTERVAL_TO_TIMEFRAME: dict[str, str] = {
    "1s": "1s",
    "5s": "5s",
    "15s": "15s",
    "30s": "30s",
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "4h",
    "4h": "4h",
    "1d": "1d",
    "5d": "1d",
    "1wk": "1w",
    "1w": "1w",
    "1mo": "1mo",
    "1y": "1mo",
}

# yfinance period -> lookback window (days) for the vault ``start`` filter.
_PERIOD_TO_DAYS: dict[str, int] = {
    "1d": 2,
    "5d": 7,
    "1mo": 31,
    "3mo": 92,
    "6mo": 183,
    "1y": 366,
    "2y": 731,
    "5y": 1826,
    "10y": 3652,
    "max": 36500,
}

_MAX_ROWS = 5000  # per-call row cap on the free plan (SDK clamps identically)


def _epoch(value: Any) -> int | None:
    """Vault bar time -> epoch seconds (accepts ISO strings or numbers)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(" ", "T")
    if text.isdigit():
        return int(text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


class LSEProvider(MarketDataProvider):
    """Read-only adapter for the London Strategic Edge vault REST API."""

    def __init__(
        self,
        api_key: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._client = client
        self._owns_client = client is None

    @property
    def name(self) -> str:
        return "London Strategic Edge"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "London Strategic Edge",
            "version": LSE_VERSION,
            "endpoint": LSE_VAULT_URL,
            "requires_api_key": True,
            "rate_limit_per_min": LSE_RATE_LIMIT,
        }

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def _rows(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """GET a synchronous vault query endpoint; row dicts or ProviderUnavailable."""
        if not self.is_configured:
            return []
        query = {key: value for key, value in params.items() if value is not None}
        try:
            response = await self._http.get(
                f"{LSE_VAULT_URL}{path}",
                params=query,
                headers={"x-api-key": self._api_key},
            )
        except Exception as exc:
            raise ProviderUnavailableError("London Strategic Edge request failed") from exc
        if response.status_code != 200:
            message = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    message = str(payload.get("detail") or payload.get("message") or "")
            except Exception:
                message = response.text[:200]
            raise ProviderUnavailableError(
                message or "London Strategic Edge request was rejected",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderUnavailableError(
                "London Strategic Edge response was malformed"
            ) from exc
        if isinstance(payload, dict):
            payload = payload.get("rows") or payload.get("data") or []
        if not isinstance(payload, list):
            raise ProviderUnavailableError(
                "London Strategic Edge response was malformed"
            )
        return [row for row in payload if isinstance(row, dict)]

    async def history(
        self,
        instrument: str,
        interval: str = "1d",
        range: str = "1y",
    ) -> list[dict[str, Any]] | None:
        """OHLCV candles from ``/vault/candles`` in chart-row shape.

        ``interval`` accepts Gateway/yfinance ids (``1m``…``1h``, ``1d``,
        ``1wk``); ``range`` accepts yfinance periods (``7d``…``5y``, ``max``).
        """
        symbol = (instrument or "").strip()
        if not self.is_configured or not symbol:
            return None
        timeframe = _INTERVAL_TO_TIMEFRAME.get((interval or "1d").lower(), "1d")
        days = _PERIOD_TO_DAYS.get(str(range or "1y").lower(), 366)
        start = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        raw = await self._rows(
            "/candles",
            {
                "symbol": symbol.upper(),
                "timeframe": timeframe,
                "order": "asc",
                "limit": _MAX_ROWS,
                "start": start,
            },
        )
        rows: list[dict[str, Any]] = []
        for bar in raw:
            # The vault labels bar-open time `ts`; `time` (epoch) is Gateway's
            # chart contract, keep both so every consumer normalizes cleanly.
            epoch = _epoch(bar.get("ts", bar.get("timestamp", bar.get("time"))))
            close = _float(bar.get("close"))
            if epoch is None or close is None:
                continue
            rows.append(
                {
                    "time": epoch,
                    "timestamp": datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(),
                    "symbol": symbol.upper(),
                    "open": _float(bar.get("open")) or close,
                    "high": _float(bar.get("high")) or close,
                    "low": _float(bar.get("low")) or close,
                    "close": close,
                    "volume": _float(bar.get("volume")) or 0.0,
                }
            )
        return rows

    async def quote(self, instrument: str) -> dict[str, Any] | None:
        """Last-trade snapshot derived from the two most recent 1m candles."""
        symbol = (instrument or "").strip()
        if not self.is_configured or not symbol:
            return None
        bars = await self._rows(
            "/candles",
            {
                "symbol": symbol.upper(),
                "timeframe": "1m",
                "order": "desc",
                "limit": 2,
            },
        )
        if not bars:
            return None
        last = bars[0]
        last_price = _float(last.get("close"))
        if last_price is None:
            return None
        previous = _float(bars[1].get("close")) if len(bars) > 1 else None
        change = last_price - previous if previous else None
        change_pct = (change / previous) * 100.0 if change is not None and previous else None
        data_time = _epoch(last.get("ts", last.get("timestamp")))
        return {
            "instrument": symbol.upper(),
            "last_price": last_price,
            "bid": None,
            "ask": None,
            "change": change,
            "change_pct": change_pct,
            "provenance": {
                "source": "London Strategic Edge",
                "provider_version": LSE_VERSION,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "data_time": (
                    datetime.fromtimestamp(data_time, tz=timezone.utc).isoformat()
                    if data_time
                    else None
                ),
                "coverage": "LSE vault tape (stocks back to 2003, FX 2009, crypto 2017)",
                "delay_seconds": 0,
                "entitlement": "lse-free-tier",
            },
        }

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
