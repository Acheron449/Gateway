"""SEC filings feed for the Overview FILINGS card.

Backed by yfinance's ``Ticker.get_sec_filings()`` (Yahoo's SEC-filings feed),
so no API key is required.  Responses are cached briefly because each symbol
costs one upstream round-trip and the Overview refetches on tab switches.

Filings kinds exposed to the UI:
- ``Watchlist``  -> filings for the requested symbol basket (the caller's
  watchlist), newest first.
- ``Recent``     -> the same rows (the UI groupings are client-side filters
  over this list: Insider = forms 4, Transcripts = none in this feed).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query

router = APIRouter(prefix="/filings", tags=["filings"])

# symbol -> (fetched_at_epoch, rows).  Small TTL: filings are daily-granular.
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_CACHE_TTL_SECONDS = 600.0


def _fetch_filings_sync(symbol: str, limit: int) -> list[dict[str, Any]]:
    """One yfinance round-trip for a symbol's SEC filings, normalized."""
    import yfinance as yf

    ticker = yf.Ticker(symbol.upper())
    getter = getattr(ticker, "get_sec_filings", None)
    if getter is None:
        # Older yfinance pins (e.g. 0.2.65 in requirements.txt) predate this
        # API — degrade to an empty feed instead of failing the card.
        return []
    raw = getter() or []
    rows: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        filed = entry.get("date")
        if isinstance(filed, datetime):
            filed_at = filed.isoformat()
        elif filed is not None:
            filed_at = str(filed)
        else:
            filed_at = None
        rows.append(
            {
                "symbol": symbol.upper(),
                "type": str(entry.get("type") or "—"),
                "date": filed_at,
                "title": str(entry.get("title") or entry.get("type") or "SEC filing"),
                "url": entry.get("edgarUrl"),
            }
        )
    rows.sort(key=lambda r: r.get("date") or "", reverse=True)
    return rows[:limit]


async def _filings_for(symbol: str, limit: int) -> list[dict[str, Any]]:
    """Cached wrapper so parallel symbol fetches don't stampede upstream."""
    key = symbol.upper()
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1][:limit]
    rows = await asyncio.to_thread(_fetch_filings_sync, key, limit)
    _CACHE[key] = (now, rows)
    return rows[:limit]


@router.get("")
async def get_filings(
    symbols: str = Query("", description="Comma-separated symbols (e.g. AAPL,MSFT)"),
    limit: int = Query(8, ge=1, le=25, description="Maximum filings per symbol"),
) -> dict[str, Any]:
    """Return recent SEC filings for a symbol basket.

    Always answers ``status=available``: an empty ``items`` array with a
    message when no symbol yielded filings (unsupported yfinance pin, no
    network, or simply nothing filed in the window).
    """
    requested = [s.strip().upper() for s in (symbols or "").split(",") if s.strip()][:12]
    if not requested:
        return {"items": [], "count": 0, "status": "available", "message": "No symbols requested"}

    items: list[dict[str, Any]] = []
    failures: list[str] = []
    for symbol in requested:
        try:
            items.extend(await _filings_for(symbol, limit))
        except Exception as exc:
            failures.append(f"{symbol}: {exc}")
    # Merge per-symbol batches back into a single newest-first feed.
    items.sort(key=lambda r: r.get("date") or "", reverse=True)
    return {
        "items": items,
        "count": len(items),
        "status": "available",
        "provenance": {
            "source": "Yahoo Finance (SEC EDGAR feed)",
            "provider_version": "yf-sec-v1",
            "entitlement": "public",
        },
        "message": "; ".join(failures) if failures and not items else None,
    }
