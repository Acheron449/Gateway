from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services import kronos_installer, kronos_service

router = APIRouter(prefix="/forecast", tags=["forecasting"])


@router.get("/kronos/install/status")
async def kronos_install_status() -> dict[str, Any]:
    """Progress of the one-click Kronos install (clone + pip + model weights)."""
    return await asyncio.to_thread(kronos_installer.status)


@router.post("/kronos/install")
async def kronos_install(force: bool = False) -> dict[str, Any]:
    """Start the one-click Kronos install in the background.

    Clones the repository, installs its requirements into the running
    interpreter, and pre-downloads the model weights. Poll the status
    endpoint for progress.
    """
    try:
        return await asyncio.to_thread(kronos_installer.start_install, force)
    except kronos_installer.KronosInstallError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
