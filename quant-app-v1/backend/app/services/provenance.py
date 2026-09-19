"""Normalized provenance fields attached to every provider-derived record."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def candle_provenance(*, source: str, data_time: int, coverage: str, delay_seconds: int | None = None) -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc)
    return {
        "source": source,
        "provider_version": "alpaca-stock-bars-v1",
        "fetched_at": fetched_at.isoformat(),
        "data_time": datetime.fromtimestamp(data_time, tz=timezone.utc).isoformat(),
        "coverage": coverage,
        "delay_seconds": delay_seconds,
        "entitlement": "configured-provider",
    }
