from __future__ import annotations

from datetime import datetime, timezone


async def fetch_latest_headlines(ticker: str, limit: int = 5) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    return [
        {"headline": f"{ticker} announces product expansion plan", "published_at": now},
        {"headline": f"Analysts upgrade {ticker} after earnings beat", "published_at": now},
    ][:limit]