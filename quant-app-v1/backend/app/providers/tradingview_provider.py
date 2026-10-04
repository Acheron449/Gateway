"""TradingView provider backed by TradingView's public chart datafeed.

This is the same unofficial websocket protocol used by open-source clients:
no subscription and no paid embed — Gateway requests the candles itself and
renders them in its own chart. The ``websockets`` module is loaded lazily
through the helper declared at the top of this file.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, Optional

from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError


def _websockets():
    """Lazy import: load websockets on first use, not at module import time."""
    import websockets

    return websockets


_DATAFEED_URL = "wss://data.tradingview.com/socket.io/websocket?from=symbols%2F&type=chart"
_ORIGIN = "https://data.tradingview.com"

# Gateway timeframe -> TradingView datafeed interval.
_INTERVAL_MAP = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "5h": "240",
    "1d": "1D",
    "1wk": "1W",
}

# Bare US tickers are tried against these exchanges in order.
_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")
_RECV_TIMEOUT_SECONDS = 15.0
_BAR_COUNT = 300

_FRAME_RE = re.compile(r"~m~(\d+)~m~")


def _connect_headers_kwarg(connect: Any) -> str:
    """websockets renamed ``extra_headers`` to ``additional_headers`` in v14;
    pick whichever this installed version accepts."""
    import inspect

    try:
        params = inspect.signature(connect).parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic signatures
        return "additional_headers"
    return "additional_headers" if "additional_headers" in params else "extra_headers"


def _frame(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, separators=(",", ":"))
    return f"~m~{len(body)}~m~{body}"


def _extract_frames(buffer: str) -> tuple[list[str], str]:
    frames: list[str] = []
    while True:
        match = _FRAME_RE.match(buffer)
        if not match:
            break
        length = int(match.group(1))
        start = match.end()
        if len(buffer) - start < length:
            break
        frames.append(buffer[start : start + length])
        buffer = buffer[start + length :]
    return frames, buffer


def _parse_candles(items: list[Any]) -> list[dict[str, Any]]:
    candles: dict[int, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        values = item.get("v")
        if not isinstance(values, list) or len(values) < 5:
            continue
        try:
            ts = int(float(values[0]))
            open_ = float(values[1])
            high = float(values[2])
            low = float(values[3])
            close = float(values[4])
            volume = float(values[5]) if len(values) > 5 and values[5] not in (None, "") else 0.0
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        candles[ts] = {
            "time": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    return [candles[ts] for ts in sorted(candles)]


async def _fetch_symbol(qualified: str, interval: str, bar_count: int = _BAR_COUNT) -> list[dict[str, Any]]:
    websockets = _websockets()
    chart_session = f"cs_{uuid.uuid4().hex[:12]}"
    series_id = "sds_1"
    collected: list[Any] = []

    async with websockets.connect(
        _DATAFEED_URL,
        **{_connect_headers_kwarg(websockets.connect): {"Origin": _ORIGIN, "User-Agent": "Mozilla/5.0"}},
        open_timeout=10,
        close_timeout=5,
        max_size=8 * 1024 * 1024,
    ) as ws:
        async def send(payload: dict[str, Any]) -> None:
            await ws.send(_frame(payload))

        await send({"m": "set_auth_token", "p": ["unauthorized_user_token"]})
        await send({"m": "chart_create_session", "p": [chart_session, ""]})
        symbol_spec = json.dumps(
            {"symbol": qualified, "adjustment": "splits", "session": "regular"},
            separators=(",", ":"),
        )
        await send({"m": "resolve_symbol", "p": [chart_session, "sds_sym_1", f"={symbol_spec}"]})
        await send(
            {"m": "create_series", "p": [chart_session, series_id, "s1", "sds_sym_1", interval, bar_count, ""]}
        )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + _RECV_TIMEOUT_SECONDS
        pending = ""
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return []
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                return []
            if isinstance(message, bytes):
                message = message.decode("utf-8", "replace")
            pending += message
            frames, pending = _extract_frames(pending)
            for frame in frames:
                if frame == "ping":
                    await ws.send("~m~4~m~ping")
                    continue
                try:
                    payload = json.loads(frame)
                except ValueError:
                    continue
                method = payload.get("m")
                params = payload.get("p")
                if not isinstance(params, list):
                    params = []
                if method in ("symbol_error", "series_error"):
                    return []
                if method in ("timescale_update", "du") and len(params) > 1:
                    block = params[1]
                    if isinstance(block, dict):
                        series = block.get(series_id)
                        if isinstance(series, dict):
                            items = series.get("s")
                            if isinstance(items, list):
                                collected.extend(items)
                elif method == "series_completed":
                    return _parse_candles(collected)


async def _fetch_history_feed(
    symbol: str, interval: str, bar_count: int = _BAR_COUNT
) -> list[dict[str, Any]]:
    candidates = [symbol] if ":" in symbol else [f"{exchange}:{symbol}" for exchange in _EXCHANGES]
    for qualified in candidates:
        try:
            candles = await _fetch_symbol(qualified, interval, bar_count)
        except Exception:
            candles = []
        if candles:
            return candles
    return []


class TradingViewProvider(MarketDataProvider):
    """TradingView public datafeed — no API key required."""

    def __init__(self, api_key: str = "", paper_trading: bool = True) -> None:
        # The public datafeed needs no credentials; api_key is accepted only
        # to satisfy the uniform registry constructor signature.
        self._api_key = api_key
        self._paper_trading = paper_trading

    @property
    def name(self) -> str:
        return "TradingView"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "TradingView",
            "version": "tv-datafeed-v1",
            "endpoint": "https://data.tradingview.com",
            "requires_api_key": False,
            "rate_limit_per_min": 60,
        }

    @property
    def is_configured(self) -> bool:
        return True

    async def history(
        self,
        instrument: str,
        interval: str = "1d",
        range: str = "1y",
    ) -> Optional[list[dict[str, Any]]]:
        tv_interval = _INTERVAL_MAP.get(str(interval).lower(), "60")
        return await _fetch_history_feed(instrument.upper(), tv_interval)

    async def quote(self, instrument: str) -> Optional[dict[str, Any]]:
        """Last price from the latest 1-minute bar (used by the key test)."""
        candles = await _fetch_history_feed(instrument.upper(), "1", bar_count=2)
        if not candles:
            raise ProviderUnavailableError(
                f"TradingView datafeed returned no data for {instrument.upper()}"
            )
        last = candles[-1]
        previous = candles[-2] if len(candles) > 1 else None
        change = last["close"] - (previous["close"] if previous else last["open"])
        base = (previous["close"] if previous else last["open"]) or last["close"]
        return {
            "symbol": instrument.upper(),
            "price": round(last["close"], 4),
            "change": round(change, 4),
            "change_pct": round((change / base * 100.0) if base else 0.0, 2),
            "provider_version": "tv-datafeed-v1",
        }
