from __future__ import annotations

from datetime import date


async def fetch_macro_snapshot() -> dict:
    return {
        "as_of": date.today().isoformat(),
        "cpi_yoy": 3.1,
        "fed_funds_rate": 5.25,
        "gdp_growth_qoq": 0.6,
    }