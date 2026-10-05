"""Yahoo Finance market-data adapter backed by the ``yfinance`` module.

This is Gateway's default chart/quote provider: it needs no API key and is
already a declared dependency.  The ``yfinance`` module is loaded lazily
through the helper declared at the top of this file, so importing the
provider (and booting the API) never pays for the dependency's startup cost.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from datetime import datetime, timezone
from typing import Any, Optional

from app.models import NewsItem
from app.providers.base import MarketDataProvider, ProviderMeta

# Yahoo's public search endpoint doubles as its news feed (the same one
# yfinance uses under the hood for ``Ticker.news``).  It needs no API key.
_YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_YF_NEWS_VERSION = "yf-news-v1"


def _yfinance():
    """Lazy import: load yfinance on first use, not at module import time."""
    import yfinance as yf

    return yf


def _fetch_yahoo_news_sync(query: str, limit: int) -> list[dict[str, Any]]:
    """Fetch raw Yahoo news articles for a ticker/search query.

    Uses yfinance's own data session (``YfData``) when available so cookies
    and crumb handling match what yfinance does for ``Ticker.news``; falls
    back to a plain GET because the search endpoint is public either way.
    """
    params = {"q": query, "newsCount": max(1, limit), "quotesCount": 0}
    articles: list[Any] = []
    try:
        from yfinance.data import YfData

        response = YfData().get(_YAHOO_SEARCH_URL, params=params)
        payload = response.json() if response is not None else None
        if isinstance(payload, dict):
            articles = payload.get("news") or []
    except Exception:
        articles = []
    if not articles:
        # Fallback: the endpoint is public, a plain GET works without a crumb.
        import requests

        response = requests.get(
            _YAHOO_SEARCH_URL,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        articles = payload.get("news") or [] if isinstance(payload, dict) else []
    return [a for a in articles if isinstance(a, dict)][:limit]


def _article_to_news_item(article: dict[str, Any], related: list[str]) -> NewsItem | None:
    """Map a raw Yahoo article dict onto the canonical NewsItem model."""
    headline = str(article.get("title") or "").strip()
    link = article.get("link")
    if not headline or not link:
        return None
    natural_id = str(article.get("uuid") or link)
    item_id = "yf-news-" + hashlib.sha256(natural_id.encode("utf-8")).hexdigest()[:24]
    published = datetime.fromtimestamp(int(article.get("providerPublishTime") or 0), tz=timezone.utc)
    if not article.get("providerPublishTime"):
        published = datetime.now(timezone.utc)
    # First thumbnail resolution is enough for the preview cards.
    thumb = None
    resolutions = ((article.get("thumbnail") or {}).get("resolutions")) or []
    if isinstance(resolutions, list) and resolutions and isinstance(resolutions[0], dict):
        thumb = resolutions[0].get("url")
    return NewsItem(
        id=item_id,
        headline=headline,
        url=str(link),
        # Publisher name (Reuters, Barrons.com, …) — provenance of the
        # Gateway fetch itself lives in the endpoint's provenance block.
        source=str(article.get("publisher") or "Yahoo Finance"),
        thumbnail=thumb,
        published_at=published,
        fetched_at=datetime.now(timezone.utc),
        categories=[str(article.get("type") or "story")],
        related_symbols=[s.upper() for s in related],
        sentiment_score=None,
        provider_version=_YF_NEWS_VERSION,
        data_time=published,
        coverage="Yahoo Finance news",
        delay_seconds=0,
        entitlement="public",
    )


def _to_epoch(value: Any) -> Optional[float]:
    """Best-effort conversion of a yfinance index/value to a UTC epoch."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    for candidate in (value,):
        ts = getattr(candidate, "timestamp", None)
        if callable(ts):
            try:
                return float(ts())
            except (ValueError, OSError, OverflowError):
                return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return None


class YahooFinanceProvider(MarketDataProvider):
    """Default credentials-free provider (Yahoo Finance via yfinance)."""

    def __init__(self, api_key: str = "", paper_trading: bool = True) -> None:
        # Yahoo Finance needs no credentials; api_key is accepted only so the
        # provider satisfies the uniform registry constructor signature.
        self._api_key = api_key
        self._paper_trading = paper_trading

    @property
    def name(self) -> str:
        return "Yahoo Finance"

    @property
    def meta(self) -> ProviderMeta:
        return {
            "name": "Yahoo Finance",
            "version": "yf-v1",
            "endpoint": "https://query1.finance.yahoo.com",
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
        """Fetch historical OHLCV bars from Yahoo Finance."""

        def _fetch() -> list[dict[str, Any]]:
            yf = _yfinance()
            frame = yf.Ticker(instrument.upper()).history(
                period=range, interval=interval, auto_adjust=False
            )
            if frame is None or frame.empty:
                return []
            candles: list[dict[str, Any]] = []
            for index, row in frame.iterrows():
                ts = _to_epoch(index)
                close = float(row.get("Close", 0) or 0)
                if ts is None or not math.isfinite(close) or close <= 0:
                    continue
                candles.append(
                    {
                        "time": int(ts),
                        "open": float(row.get("Open", close) or close),
                        "high": float(row.get("High", close) or close),
                        "low": float(row.get("Low", close) or close),
                        "close": close,
                        "volume": float(row.get("Volume", 0) or 0),
                    }
                )
            candles.sort(key=lambda c: c["time"])
            return candles

        return await asyncio.to_thread(_fetch)

    async def quote(self, instrument: str) -> Optional[dict[str, Any]]:
        """Last-price snapshot via yfinance ``fast_info``."""

        def _fetch() -> dict[str, Any] | None:
            yf = _yfinance()
            symbol = instrument.upper()
            fast = yf.Ticker(symbol).fast_info
            price = float(fast.last_price or 0)
            prev = float(fast.previous_close or 0)
            if not math.isfinite(price) or price <= 0:
                return None
            change = price - prev if prev > 0 else 0.0
            return {
                "symbol": symbol,
                "price": round(price, 4),
                "change": round(change, 4),
                "change_pct": round((change / prev * 100.0) if prev > 0 else 0.0, 2),
                "provider_version": "yf-v1",
            }

        return await asyncio.to_thread(_fetch)

    async def news(
        self,
        symbol: str | None = None,
        limit: int = 5,
    ) -> list[NewsItem]:
        """Headlines from Yahoo Finance via the yfinance data layer.

        Keyless by design: the general (symbol-less) call searches top
        business headlines, and per-symbol calls narrow to one ticker so the
        news service's fan-out dedupes across its symbol basket.
        """
        if limit <= 0:
            return []
        query = (symbol or "").strip().upper() or "finance markets"

        def _fetch() -> list[NewsItem]:
            try:
                articles = _fetch_yahoo_news_sync(query, limit)
            except Exception as exc:
                # Surface as the canonical provider error so the news chain
                # can move on to the next source.
                from app.providers.base import ProviderUnavailableError

                raise ProviderUnavailableError(f"Yahoo Finance news request failed: {exc}") from exc
            related = [symbol.upper()] if symbol else []
            items: list[NewsItem] = []
            for article in articles:
                record = _article_to_news_item(article, related)
                if record is not None:
                    items.append(record)
            return items

        return await asyncio.to_thread(_fetch)
