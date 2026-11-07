"""Quant modules: Monte Carlo risk simulation (SRS §5.1, FR-M1..M7).

The route accepts a stored run id (owner-scoped) **or** an explicit return
series / equity curve. The series is hashed into the response so a caller can
prove they simulated the same data twice.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.services import database
from app.services import quant_monte_carlo as engine

router = APIRouter(prefix="/quant", tags=["quant"])


class MonteCarloRequest(BaseModel):
    run_id: str | None = None
    returns: list[float] | None = None
    equity_curve: list[float] | None = None
    paths: int = Field(default=engine.DEFAULT_PATHS, ge=1, le=engine.MAX_PATHS)
    horizon: int | None = Field(default=None, ge=1, le=engine.MAX_HORIZON)
    seed: int = Field(default=42, ge=0, le=2**63 - 1)
    method: str = engine.DEFAULT_METHOD
    block_length: int = Field(default=engine.DEFAULT_BLOCK_LENGTH, ge=1, le=engine.MAX_BLOCK_LENGTH)
    start_equity: float | None = Field(default=None, gt=0)
    ruin_fraction: float = Field(default=engine.DEFAULT_RUIN_FRACTION, ge=0, le=1)
    periods_per_year: int = Field(default=engine.DEFAULT_PERIODS_PER_YEAR, ge=1, le=100_000)
    risk_budget: float | None = Field(default=None, ge=0)


def _bad_request(message: str, code: str = "invalid_request") -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


@router.post("/monte-carlo")
async def monte_carlo(payload: MonteCarloRequest, user: CurrentUser) -> dict[str, Any]:
    """Simulate fan, tail risk, drawdown distribution, ruin and sizing."""
    sources = [
        payload.run_id is not None,
        payload.returns is not None,
        payload.equity_curve is not None,
    ]
    if sum(1 for source in sources if source) != 1:
        raise _bad_request("supply exactly one of run_id, returns or equity_curve", "input_required")

    response_extra: dict[str, Any] = {"source": "returns"}
    returns = payload.returns
    equity_curve = payload.equity_curve
    start_equity = payload.start_equity
    horizon = payload.horizon

    if payload.run_id is not None:
        row = database.get_backtest_receipt(payload.run_id, user.id)
        if row is None:
            # Another account's run is indistinguishable from a missing one.
            raise HTTPException(status_code=404, detail=f"Backtest run '{payload.run_id}' not found")
        result = row.get("result") or {}
        curve = [
            float(point["equity"])
            for point in (result.get("equity_curve") or [])
            if isinstance(point, dict) and point.get("equity") is not None
        ]
        if len(curve) < 2:
            raise _bad_request(
                "that run has no equity curve to resample; supply returns instead",
                "no_equity_curve",
            )
        receipt = row.get("receipt") or {}
        returns = None
        equity_curve = curve
        start_equity = payload.start_equity or float(receipt.get("initial_capital") or curve[0])
        if horizon is None:
            horizon = min(engine.MAX_HORIZON, len(curve) - 1)
        response_extra = {
            "source": "run",
            "run_id": payload.run_id,
            "receipt_data_hash": row.get("data_hash") or receipt.get("data_hash"),
        }

    try:
        result = await asyncio.to_thread(
            engine.simulate,
            returns=returns,
            equity_curve=equity_curve,
            start_equity=start_equity,
            horizon=horizon,
            paths=payload.paths,
            seed=payload.seed,
            method=payload.method,
            block_length=payload.block_length,
            ruin_fraction=payload.ruin_fraction,
            periods_per_year=payload.periods_per_year,
            risk_budget=payload.risk_budget,
        )
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc

    return {**response_extra, **result}
