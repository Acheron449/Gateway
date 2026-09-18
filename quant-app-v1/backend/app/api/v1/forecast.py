from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services import kronos_service

router = APIRouter(prefix="/forecast", tags=["forecasting"])


@router.post("/kronos")
async def kronos_forecast(payload: dict[str, Any]) -> dict[str, Any]:
    """Forecast supplied Gateway OHLC candles with an optional Kronos deployment."""
    try:
        forecast = await asyncio.to_thread(
            kronos_service.forecast,
            payload.get("bars", []),
            int(payload.get("horizon", 20)),
            str(payload.get("frequency", "D")),
            int(payload.get("sample_count", 1)),
        )
    except kronos_service.KronosUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    records = forecast.reset_index().to_dict(orient="records")
    return {"provider": "kronos", "horizon": len(records), "forecast": records}
