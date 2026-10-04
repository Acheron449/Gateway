"""Normalized provenance fields attached to every provider-derived record."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

UTC_ISO = "%Y-%m-%dT%H:%M:%S.%fZ"

# Source id -> provider version reported to the UI.
_PROVIDER_VERSIONS: dict[str, str] = {
    "yfinance": "yf-v1",
    "yahoo": "yf-v1",
    "yahoo-finance": "yf-v1",
    "alpaca": "alpaca-stock-bars-v1",
    "openbb": "openbb-v1",
    "openbb-server": "openbb-api-v1",
}


def candle_provenance(*, source: str, data_time: int, coverage: str, delay_seconds: int | None = None) -> dict[str, Any]:
    fetched_at = datetime.now(timezone.utc)
    return {
        "source": source,
        "provider_version": _PROVIDER_VERSIONS.get(source, f"{source}-v1"),
        "fetched_at": fetched_at.isoformat(),
        "data_time": datetime.fromtimestamp(data_time, tz=timezone.utc).isoformat(),
        "coverage": coverage,
        "delay_seconds": delay_seconds,
        "entitlement": "configured-provider",
    }
