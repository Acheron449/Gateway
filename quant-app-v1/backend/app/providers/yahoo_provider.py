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

from app.models import EconomicEvent, EventImportance, NewsItem
from app.providers.base import MarketDataProvider, ProviderMeta, ProviderUnavailableError
from app.services.as_of import filter_timestamped_rows, normalize_as_of

# Yahoo's public search endpoint doubles as its news feed (the same one
# yfinance uses under the hood for ``Ticker.news``).  It needs no API key.
_YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_YF_NEWS_VERSION = "yf-news-v1"
_YF_CALENDAR_VERSION = "yf-calendar-v1"

_COUNTRY_CURRENCY = {
    "US": ("US", "USD"), "USA": ("US", "USD"), "UNITED STATES": ("US", "USD"),
    "GB": ("GB", "GBP"), "UK": ("GB", "GBP"), "UNITED KINGDOM": ("GB", "GBP"),
    "CA": ("CA", "CAD"), "CANADA": ("CA", "CAD"),
    "JP": ("JP", "JPY"), "JAPAN": ("JP", "JPY"),
    "CN": ("CN", "CNY"), "CHINA": ("CN", "CNY"),
    "AU": ("AU", "AUD"), "AUSTRALIA": ("AU", "AUD"),
    "NZ": ("NZ", "NZD"), "NEW ZEALAND": ("NZ", "NZD"),
    "CH": ("CH", "CHF"), "SWITZERLAND": ("CH", "CHF"),
    "EU": ("EU", "EUR"), "EURO AREA": ("EU", "EUR"), "EUROZONE": ("EU", "EUR"),
    "DE": ("DE", "EUR"), "GERMANY": ("DE", "EUR"),
    "FR": ("FR", "EUR"), "FRANCE": ("FR", "EUR"),
    "IT": ("IT", "EUR"), "ITALY": ("IT", "EUR"),
    "ES": ("ES", "EUR"), "SPAIN": ("ES", "EUR"),
    "IN": ("IN", "INR"), "INDIA": ("IN", "INR"),
    "BR": ("BR", "BRL"), "BRAZIL": ("BR", "BRL"),
    "MX": ("MX", "MXN"), "MEXICO": ("MX", "MXN"),
    "KR": ("KR", "KRW"), "SOUTH KOREA": ("KR", "KRW"),
    "ZA": ("ZA", "ZAR"), "SOUTH AFRICA": ("ZA", "ZAR"),
    "TR": ("TR", "TRY"), "TURKEY": ("TR", "TRY"),
    # Common ISO-3166 region codes returned directly by Yahoo's calendar feed.
    "AE": ("AE", "AED"), "AR": ("AR", "ARS"), "BD": ("BD", "BDT"),
    "BG": ("BG", "BGN"), "CL": ("CL", "CLP"), "CO": ("CO", "COP"),
    "CZ": ("CZ", "CZK"), "DK": ("DK", "DKK"), "HK": ("HK", "HKD"),
    "HU": ("HU", "HUF"), "ID": ("ID", "IDR"), "IS": ("IS", "ISK"),
    "IL": ("IL", "ILS"), "KW": ("KW", "KWD"), "KZ": ("KZ", "KZT"),
    "LK": ("LK", "LKR"), "MA": ("MA", "MAD"), "MY": ("MY", "MYR"),
    "NG": ("NG", "NGN"), "NO": ("NO", "NOK"), "OM": ("OM", "OMR"),
    "PE": ("PE", "PEN"), "PH": ("PH", "PHP"), "PK": ("PK", "PKR"),
    "PL": ("PL", "PLN"), "PT": ("PT", "EUR"), "QA": ("QA", "QAR"),
    "RO": ("RO", "RON"), "RU": ("RU", "RUB"), "SA": ("SA", "SAR"),
    "SE": ("SE", "SEK"), "SG": ("SG", "SGD"), "TH": ("TH", "THB"),
    "TW": ("TW", "TWD"), "UA": ("UA", "UAH"), "VN": ("VN", "VND"),
    "EG": ("EG", "EGP"), "KE": ("KE", "KES"), "GH": ("GH", "GHS"),
}


def _finite_number(value: Any) -> float | None:
    """Return finite numeric values, excluding pandas NA/NaN and placeholders."""
    if value is None:
        return None
    try:
        if value != value:  # NaN, including numpy/pandas scalar NaNs
            return None
    except (TypeError, ValueError):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _calendar_time(value: Any) -> datetime | None:
    """Parse a release timestamp; date-only values are not precise enough."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text or len(text) <= 10:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _region_country_currency(value: Any) -> tuple[str, str]:
    region = str(value or "").strip()
    known = _COUNTRY_CURRENCY.get(region.upper())
    return known if known else (region, "")


def _yahoo_calendar_events(frame: Any, limit: int) -> list[EconomicEvent]:
    """Normalize yfinance's DataFrame calendar into canonical events."""
    if frame is None or getattr(frame, "empty", True):
        return []
    if not hasattr(frame, "iterrows"):
        raise ValueError("Yahoo Finance calendar returned an invalid result")
    events: list[EconomicEvent] = []
    for event_name, row in frame.iterrows():
        title = str(event_name or "").strip()
        scheduled_at = _calendar_time(row.get("Event Time"))
        if not title or scheduled_at is None:
            continue
        country, currency = _region_country_currency(row.get("Region"))
        actual = _finite_number(row.get("Actual"))
        forecast = _finite_number(row.get("Expected"))
        prior = _finite_number(row.get("Last"))
        revised = _finite_number(row.get("Revised"))
        revisions = ([{"timestamp": scheduled_at.isoformat(), "value": revised}]
                     if revised is not None and revised != prior else [])
        natural_key = "|".join((title.casefold(), scheduled_at.isoformat(), country.casefold()))
        event_id = "yf-cal-" + hashlib.sha256(natural_key.encode("utf-8")).hexdigest()[:24]
        events.append(EconomicEvent(
            id=event_id,
            title=title,
            country=country,
            currency=currency,
            importance=EventImportance.MEDIUM,
            scheduled_at=scheduled_at,
            actual=actual,
            forecast=forecast,
            prior=prior,
            revisions=revisions,
            related_symbols=[],
            provider_version=_YF_CALENDAR_VERSION,
            source="Yahoo Finance",
            fetched_at=datetime.now(timezone.utc),
            data_time=scheduled_at,
            coverage="Global economic events (best effort)",
            delay_seconds=None,
            entitlement="public",
        ))
        if len(events) >= max(1, min(limit, 100)):
            break
    return events


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
    def calendar_version(self) -> str:
        return _YF_CALENDAR_VERSION

    @property
    def is_configured(self) -> bool:
        return True

    async def history(
        self,
        instrument: str,
        interval: str = "1d",
        range: str = "1y",
        *,
        as_of: datetime | None = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Fetch historical OHLCV bars from Yahoo Finance."""

        def _fetch() -> list[dict[str, Any]]:
            yf = _yfinance()
            cutoff = normalize_as_of(as_of)
            frame = yf.Ticker(instrument.upper()).history(
                period=range,
                interval=interval,
                end=cutoff.replace(tzinfo=None) if cutoff else None,
                auto_adjust=False,
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
            return filter_timestamped_rows(candles, as_of=as_of)

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

    async def calendar(
        self,
        limit: int = 5,
        *,
        as_of: datetime | None = None,
    ) -> list[EconomicEvent]:
        """Fetch best-effort public economic events from yfinance's calendar API."""
        if limit <= 0:
            return []

        def _fetch() -> list[EconomicEvent]:
            yf = _yfinance()
            calendars = getattr(yf, "Calendars", None)
            if not callable(calendars):
                raise ProviderUnavailableError("Yahoo Finance calendar API is unavailable")
            try:
                frame = calendars().get_economic_events_calendar(limit=min(limit, 100))
                events = _yahoo_calendar_events(frame, 100 if as_of is not None else limit)
                cutoff = normalize_as_of(as_of)
                if cutoff is not None:
                    events = [event for event in events if event.scheduled_at <= cutoff]
                return events[:limit]
            except ProviderUnavailableError:
                raise
            except Exception as exc:
                raise ProviderUnavailableError(f"Yahoo Finance calendar request failed: {exc}") from exc

        return await asyncio.to_thread(_fetch)

    async def news(
        self,
        symbol: str | None = None,
        limit: int = 5,
        *,
        as_of: datetime | None = None,
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
                if record is not None and (as_of is None or record.published_at <= normalize_as_of(as_of)):
                    items.append(record)
            return items

        return await asyncio.to_thread(_fetch)
