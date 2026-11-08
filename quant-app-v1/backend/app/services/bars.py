"""Historical bars for backtests and bots (single Yahoo source, FR-D1).

Kept separate from the chart route so a background bot never reaches into the
HTTP layer. Bars are normalised to ``{time, open, high, low, close, volume}``
with epoch-second timestamps, which is what the engine hashes.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

# timeframe -> (yfinance interval, max period)
YF_TIMEFRAMES = {
    "1m": ("1m", "5d"),
    "5m": ("5m", "1mo"),
    "15m": ("15m", "3mo"),
    "30m": ("30m", "6mo"),
    "1h": ("1h", "2y"),
    "4h": ("1h", "2y"),
    "1d": ("1d", "10y"),
    "1w": ("1wk", "10y"),
}


class BarsUnavailable(RuntimeError):
    """No bars could be produced for the request."""


def _normalize_frame(frame: Any) -> list[dict]:
    bars: list[dict] = []
    if frame is None or getattr(frame, "empty", True):
        return bars
    for index, row in frame.iterrows():
        try:
            epoch = int(index.timestamp())
            bars.append(
                {
                    "time": epoch,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row.get("Volume", 0) or 0),
                }
            )
        except Exception:
            continue
    bars.sort(key=lambda b: b["time"])
    return bars


def _resample_four_hour(bars: list[dict]) -> list[dict]:
    if not bars:
        return bars
    buckets: dict[int, dict] = {}
    for bar in bars:
        key = bar["time"] - (bar["time"] % (4 * 3600))
        bucket = buckets.get(key)
        if bucket is None:
            buckets[key] = {
                "time": key,
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
            }
        else:
            bucket["high"] = max(bucket["high"], bar["high"])
            bucket["low"] = min(bucket["low"], bar["low"])
            bucket["close"] = bar["close"]
            bucket["volume"] += bar["volume"]
    return [buckets[key] for key in sorted(buckets)]


def fetch_bars(symbol: str, timeframe: str = "1h", limit: int = 500) -> list[dict]:
    """Fetch the most recent ``limit`` bars; raise BarsUnavailable on outage."""
    import yfinance as yf

    tf = (timeframe or "1h").lower()
    interval, period = YF_TIMEFRAMES.get(tf, YF_TIMEFRAMES["1h"])
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise BarsUnavailable("symbol is required")
    try:
        frame = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    except Exception as exc:
        logger.warning("Bar fetch failed for {}: {}", symbol, exc)
        raise BarsUnavailable(f"history unavailable for {symbol}") from exc

    bars = _normalize_frame(frame)
    if tf == "4h":
        bars = _resample_four_hour(bars)
    if not bars:
        raise BarsUnavailable(f"no bars returned for {symbol}")
    return bars[-max(1, int(limit)):]
