from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.models import OrderSide, OrderStatus, OrderType
from app.auth import CurrentUser, decode_token
from app.services.database import (
    create_portfolio,
    get_portfolio,
    get_portfolio_history,
)
from app.services.fill_simulator import FillSimulator, get_market_session, is_market_open
from app.services.portfolio_risk import build_portfolio_risk

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


DEFAULT_PORTFOLIO_PREFIX = "paper_"

_fill_simulator = FillSimulator()


class OrderRequest(BaseModel):
    instrument: str = Field(min_length=1, max_length=12)
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: float = Field(gt=0)
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    strategy_version_id: str | None = None


class OrderResponse(BaseModel):
    order_id: str
    status: OrderStatus
    message: str


class PortfolioResponse(BaseModel):
    portfolio_id: str
    cash: float
    equity: float
    buying_power: float
    positions: list[dict[str, Any]]
    open_orders: list[dict[str, Any]]
    recent_fills: list[dict[str, Any]]


def _get_default_portfolio(user_id: str) -> str:
    """Return the signed-in user's paper portfolio, creating it on first use.

    The id embeds the verified user id so two accounts can never resolve to the
    same book (SRS NFR-6). A row with that id but a different owner is treated
    as a conflict, never exposed.
    """
    portfolio_id = f"{DEFAULT_PORTFOLIO_PREFIX}{user_id}"
    portfolio = get_portfolio(portfolio_id)
    if portfolio is None:
        create_portfolio(portfolio_id, user_id)
        portfolio = get_portfolio(portfolio_id)
    if portfolio is None or portfolio.get("user_id") != user_id:
        raise HTTPException(status_code=409, detail="Portfolio ownership conflict")
    return portfolio_id


def _require_owned_portfolio(portfolio_id: str, user_id: str) -> dict[str, Any]:
    portfolio = get_portfolio(portfolio_id)
    if not portfolio or portfolio.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


class EquityCurvePoint(BaseModel):
    time: str
    equity: float
    cash: float


class DrawdownCurvePoint(BaseModel):
    time: str
    drawdown: float


class ConcentrationRow(BaseModel):
    symbol: str
    pct: float


class RiskPositionRow(BaseModel):
    instrument_id: str
    quantity: float
    avg_cost: float
    market_value: float
    unrealized_pnl: float
    realized_pnl: float
    pct_of_equity: float


class PortfolioRiskResponse(BaseModel):
    """Owner-scoped risk payload, replayed from this portfolio's own records."""

    portfolio_id: str
    generated_at: str
    equity: float
    cash: float
    buying_power: float
    daily_pnl: float
    daily_pnl_pct: float
    total_return_pct: float
    max_drawdown: float
    current_drawdown: float
    open_positions: int
    gross_exposure: float
    net_exposure: float
    var_95: float
    var_99: float
    var_95_amount: float
    var_99_amount: float
    concentration_risk: list[ConcentrationRow]
    equity_curve: list[EquityCurvePoint]
    drawdown_curve: list[DrawdownCurvePoint]
    positions: list[RiskPositionRow]
    series_note: str


@router.get("", response_model=PortfolioResponse)
async def get_portfolio_state(user: CurrentUser) -> PortfolioResponse:
    portfolio_id = _get_default_portfolio(user.id)
    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return PortfolioResponse(
        portfolio_id=portfolio_id,
        cash=portfolio.get("cash", 0),
        equity=portfolio.get("equity", 0),
        buying_power=portfolio.get("buying_power", 0),
        positions=portfolio.get("positions", []),
        open_orders=portfolio.get("open_orders", []),
        recent_fills=portfolio.get("recent_fills", []),
    )


@router.get("/history")
async def get_portfolio_history_endpoint(user: CurrentUser, limit: int = Query(100, ge=1, le=1000)) -> list[dict[str, Any]]:
    portfolio_id = _get_default_portfolio(user.id)
    return get_portfolio_history(portfolio_id, limit)


@router.get("/risk", response_model=PortfolioRiskResponse)
async def get_portfolio_risk(user: CurrentUser) -> PortfolioRiskResponse:
    """Equity curve, drawdown path and risk metrics for the caller's book.

    Derived from the owner-scoped paper portfolio's ledger and fill events, so
    the dashboard charts real recorded history instead of demo numbers.
    """
    portfolio_id = _get_default_portfolio(user.id)
    return PortfolioRiskResponse(**build_portfolio_risk(portfolio_id))


@router.post("/orders", response_model=OrderResponse)
async def submit_order(request: OrderRequest, user: CurrentUser) -> OrderResponse:
    """Admit one simulated order through the shared gate (FR-T2).

    The route deliberately contains no risk logic of its own: it calls
    :func:`admit_order`, the same path the bot runner uses, so the kill switch
    and cash reservation cannot be bypassed by one caller.
    """
    portfolio_id = _get_default_portfolio(user.id)
    if not get_portfolio(portfolio_id):
        raise HTTPException(status_code=404, detail="Portfolio not found")

    from app.services.order_admission import AdmissionError, admit_order

    try:
        decision = admit_order(
            portfolio_id=portfolio_id,
            instrument=request.instrument,
            side=request.side,
            order_type=request.order_type,
            qty=request.quantity,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            strategy_version_id=request.strategy_version_id,
            source="api",
        )
    except AdmissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if decision.accepted:
        return OrderResponse(
            order_id=decision.order_id or "",
            status=OrderStatus.ACCEPTED,
            message="Simulated order accepted and acknowledged",
        )
    if decision.status == "blocked":
        raise HTTPException(status_code=403, detail=decision.reason or "Kill switch active")
    if decision.status == "unavailable":
        raise HTTPException(status_code=503, detail=decision.reason or "Market data is unavailable")
    raise HTTPException(
        status_code=400, detail=f"Risk check failed: {decision.reason or 'rejected'}"
    )


class FillSimulationResponse(BaseModel):
    filled: bool
    fill_id: str | None = None
    qty: float | None = None
    price: float | None = None
    commission: float | None = None
    liquidity: str | None = None
    session: str | None = None


class MarketStatusResponse(BaseModel):
    session: str
    is_open: bool


@router.post("/orders/{order_id}/simulate-fill", response_model=FillSimulationResponse)
async def simulate_fill_endpoint(order_id: str, user: CurrentUser) -> FillSimulationResponse:
    portfolio_id = _get_default_portfolio(user.id)
    result = _fill_simulator.try_fill_order(portfolio_id, order_id)
    if result:
        return FillSimulationResponse(
            filled=True,
            fill_id=result["fill_id"],
            qty=result["qty"],
            price=result["price"],
            commission=result["commission"],
            liquidity=result["liquidity"],
            session=result["session"],
        )
    return FillSimulationResponse(filled=False)


@router.get("/market-status", response_model=MarketStatusResponse)
async def get_market_status(user: CurrentUser) -> MarketStatusResponse:
    session = get_market_session()
    return MarketStatusResponse(
        session=session.value,
        is_open=is_market_open(),
    )


@router.get("/fill-simulator/config")
async def get_fill_sim_config(user: CurrentUser) -> dict:
    return {
        "slippage": {
            "base_bps": _fill_simulator.config.slippage.base_bps,
            "volatility_multiplier": _fill_simulator.config.slippage.volatility_multiplier,
            "size_impact_bps_per_10k": _fill_simulator.config.slippage.size_impact_bps_per_10k,
            "spread_capture_pct": _fill_simulator.config.slippage.spread_capture_pct,
        },
        "commission": {
            "per_share": _fill_simulator.config.commission.per_share,
            "min_per_order": _fill_simulator.config.commission.min_per_order,
            "max_pct_of_trade": _fill_simulator.config.commission.max_pct_of_trade,
        },
        "partial_fill_probability": _fill_simulator.config.partial_fill_probability,
        "max_partial_fill_pct": _fill_simulator.config.max_partial_fill_pct,
    }


@router.get("/{portfolio_id}", response_model=dict)
async def get_portfolio_detail(portfolio_id: str, user: CurrentUser) -> dict:
    return _require_owned_portfolio(portfolio_id, user.id)


@router.websocket("/stream")
async def portfolio_websocket(websocket: WebSocket) -> None:
    """Authenticate from a first frame, then report streaming as unavailable.

    Polling ``GET /portfolio`` is the supported live view; this socket never
    carried owner-scoped updates, so it fails closed instead of pretending to.
    """
    if websocket.query_params.get("token"):
        await websocket.close(code=4001, reason="Token query parameters are not accepted")
        return
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        await websocket.close(code=4001, reason="Authentication required")
        return
    if not isinstance(payload, dict) or payload.get("type") != "authenticate":
        await websocket.close(code=4001, reason="Authentication required")
        return
    token = payload.get("token")
    if not isinstance(token, str) or not token.strip():
        await websocket.close(code=4001, reason="Authentication required")
        return
    token_data = decode_token(token.strip())
    if not token_data or token_data.exp < datetime.now(timezone.utc):
        await websocket.close(code=4001, reason="Invalid or expired token")
        return
    await websocket.send_json({
        "type": "error",
        "message": "Portfolio streaming is unavailable; poll GET /portfolio",
    })
    await websocket.close(code=1013, reason="Streaming unavailable")
