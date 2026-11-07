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
from app.services import quant_options as options_engine
from app.services import quant_orderbook as orderbook_engine

router = APIRouter(prefix="/quant", tags=["quant"])


class MonteCarloRequest(BaseModel):
    run_id: str | None = None
    returns: list[float] | None = Field(default=None, max_length=engine.MAX_OBSERVATIONS)
    equity_curve: list[float] | None = Field(default=None, max_length=engine.MAX_OBSERVATIONS)
    paths: int = Field(default=engine.DEFAULT_PATHS, ge=1, le=engine.MAX_PATHS)
    horizon: int | None = Field(default=None, ge=1, le=engine.MAX_HORIZON)
    seed: int = Field(default=42, ge=0, le=2**63 - 1)
    method: str = engine.DEFAULT_METHOD
    block_length: int = Field(default=engine.DEFAULT_BLOCK_LENGTH, ge=1, le=engine.MAX_BLOCK_LENGTH)
    start_equity: float | None = Field(default=None, gt=0)
    ruin_fraction: float = Field(default=engine.DEFAULT_RUIN_FRACTION, ge=0, le=1)
    periods_per_year: int = Field(default=engine.DEFAULT_PERIODS_PER_YEAR, ge=1, le=100_000)
    risk_budget: float | None = Field(default=None, ge=0)


class OptionPriceRequest(BaseModel):
    """FR-O1: S, K, T, r, q, sigma, type."""

    S: float
    K: float
    T: float
    r: float
    q: float = 0.0
    sigma: float
    type: str = "call"


class OptionImpliedVolRequest(BaseModel):
    """FR-O2: a market price plus the contract, minus sigma."""

    market_price: float
    S: float
    K: float
    T: float
    r: float
    q: float = 0.0
    type: str = "call"


class OrderBookRequest(BaseModel):
    """FR-L1: the price context the ladder is simulated around."""

    mid: float
    seed: int = 7
    agents: int = orderbook_engine.DEFAULT_AGENTS
    weights: dict[str, float] | None = None
    recent_return: float = 0.0
    lookback_return: float | None = None
    lookback_volatility: float | None = None
    inventory: float = 0.0
    spread_base: float = orderbook_engine.DEFAULT_SPREAD_BASE
    spread_cv: float = orderbook_engine.DEFAULT_SPREAD_CV
    band: float = orderbook_engine.DEFAULT_BAND
    inventory_penalty: float = orderbook_engine.DEFAULT_INVENTORY_PENALTY
    tick: float = orderbook_engine.DEFAULT_TICK
    size_scale: float = orderbook_engine.DEFAULT_SIZE_SCALE
    large_distance: float = orderbook_engine.DEFAULT_LARGE_DISTANCE


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


@router.post("/options/price")
async def options_price(payload: OptionPriceRequest, _user: CurrentUser) -> dict[str, Any]:
    """European Black-Scholes value, greeks and model boundaries (FR-O1, FR-O4)."""
    try:
        return await asyncio.to_thread(
            options_engine.price,
            S=payload.S,
            K=payload.K,
            T=payload.T,
            r=payload.r,
            q=payload.q,
            sigma=payload.sigma,
            kind=payload.type,
        )
    except options_engine.OptionInputError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_field", "field": exc.field, "message": exc.message},
        ) from exc


@router.post("/options/implied-vol")
async def options_implied_vol(
    payload: OptionImpliedVolRequest, _user: CurrentUser
) -> dict[str, Any]:
    """Solve for implied volatility with an explicit convergence status (FR-O2)."""
    try:
        return await asyncio.to_thread(
            options_engine.implied_volatility,
            market_price=payload.market_price,
            S=payload.S,
            K=payload.K,
            T=payload.T,
            r=payload.r,
            q=payload.q,
            kind=payload.type,
        )
    except options_engine.ImpliedVolBoundError as exc:
        # §5.2: a price outside the no-arbitrage band is a 422 naming the bound,
        # never a silent clamp.
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.code,
                "field": exc.field,
                "bound": exc.bound,
                "message": exc.message,
            },
        ) from exc
    except options_engine.OptionInputError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_field", "field": exc.field, "message": exc.message},
        ) from exc


@router.post("/orderbook/simulate")
async def orderbook_simulate(payload: OrderBookRequest, _user: CurrentUser) -> dict[str, Any]:
    """Simulated bid/ask ladder with per-archetype attribution (FR-L1..L6)."""
    try:
        return await asyncio.to_thread(
            orderbook_engine.simulate,
            mid=payload.mid,
            seed=payload.seed,
            agents=payload.agents,
            weights=payload.weights,
            recent_return=payload.recent_return,
            lookback_return=payload.lookback_return,
            lookback_volatility=payload.lookback_volatility,
            inventory=payload.inventory,
            spread_base=payload.spread_base,
            spread_cv=payload.spread_cv,
            band=payload.band,
            inventory_penalty=payload.inventory_penalty,
            tick=payload.tick,
            size_scale=payload.size_scale,
            large_distance=payload.large_distance,
        )
    except orderbook_engine.OrderBookInputError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_field", "field": exc.field, "message": exc.message},
        ) from exc
