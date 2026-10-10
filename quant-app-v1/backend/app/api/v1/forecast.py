from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services import kronos_installer, kronos_service

router = APIRouter(prefix="/forecast", tags=["forecasting"])


@router.get("/kronos/install/status")
async def kronos_install_status() -> dict[str, Any]:
    """Progress of the one-click Kronos install (clone + pip + model weights)."""
    return await asyncio.to_thread(kronos_installer.status)


@router.post("/kronos/install")
async def kronos_install(force: bool = False, path: str | None = None) -> dict[str, Any]:
    """Start the one-click Kronos install in the background.

    Clones the repository, installs its requirements into the running
    interpreter, and pre-downloads the model weights. ``path`` is the save
    location the user picked in the installer popup. Poll the status endpoint
    for progress.
    """
    try:
        return await asyncio.to_thread(kronos_installer.start_install, force, path)
    except kronos_installer.KronosInstallError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/kronos/local-server")
async def kronos_local_server() -> dict[str, Any]:
    """Whether a locally running Kronos inference server can take predictions.

    Item 12: lets the site predict against ``KRONOS_SERVER_URL`` (default
    ``http://127.0.0.1:8765``) instead of loading the model in-process.
    """
    return await asyncio.to_thread(kronos_service.local_server_status)


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

    # Round-trip through JSON so pandas Timestamps/NaNs become plain values —
    # FastAPI cannot serialise them directly.
    records = json.loads(forecast.reset_index().to_json(orient="records", date_format="iso"))
    return {"provider": "kronos", "horizon": len(records), "forecast": records}
