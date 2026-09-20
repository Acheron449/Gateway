from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.models import OrderSide, OrderStatus, OrderType
from app.services.database import (
    create_portfolio,
    get_portfolio,
    get_portfolio_history,
)
from app.services.paper_portfolio import PaperPortfolioService
from app.services.risk_engine import RiskCheckResult, get_risk_engine

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


DEFAULT_PORTFOLIO_ID = "paper_default"
DEFAULT_USER_ID = "default_user"


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


def _get_default_portfolio() -> str:
    portfolio = get_portfolio(DEFAULT_PORTFOLIO_ID)
    if not portfolio:
        create_portfolio(DEFAULT_PORTFOLIO_ID, DEFAULT_USER_ID)
    return DEFAULT_PORTFOLIO_ID


def _get_current_price(instrument: str) -> float:
    try:
        from app.services.market_data import get_quote
        quote = get_quote(instrument)
        if quote and quote.last_price:
            return quote.last_price
    except Exception:
        pass
    return 100.0


@router.get("", response_model=PortfolioResponse)
async def get_portfolio_state() -> PortfolioResponse:
    portfolio_id = _get_default_portfolio()
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
async def get_portfolio_history_endpoint(limit: int = Query(100, ge=1, le=1000)) -> list[dict[str, Any]]:
    portfolio_id = _get_default_portfolio()
    return get_portfolio_history(portfolio_id, limit)


@router.post("/orders", response_model=OrderResponse)
async def submit_order(request: OrderRequest) -> OrderResponse:
    portfolio_id = _get_default_portfolio()
    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    current_price = _get_current_price(request.instrument)

    from app.models import Order
    order = Order(
        id="",
        instrument=request.instrument.upper(),
        side=request.side,
        order_type=request.order_type,
        quantity=request.quantity,
        limit_price=request.limit_price,
        stop_price=request.stop_price,
        account_id=portfolio_id,
        execution_mode="paper",
        status=OrderStatus.PENDING_NEW,
    )

    risk_engine = get_risk_engine()
    result, violations = risk_engine.check_order(portfolio_id, order, current_price)

    if result == RiskCheckResult.KILL_SWITCH:
        raise HTTPException(status_code=403, detail=f"Kill switch active: {violations[0].message}")
    if result == RiskCheckResult.REJECTED:
        messages = "; ".join(v.message for v in violations)
        raise HTTPException(status_code=400, detail=f"Risk check failed: {messages}")

    service = PaperPortfolioService(portfolio_id)
    submitted_order = service.submit_order(
        instrument_id=request.instrument.upper(),
        side=request.side,
        order_type=request.order_type,
        qty=request.quantity,
        limit_price=request.limit_price,
        stop_price=request.stop_price,
        strategy_version_id=request.strategy_version_id,
    )

    service.acknowledge_order(submitted_order.id)

    return OrderResponse(
        order_id=submitted_order.id,
        status=OrderStatus.ACCEPTED,
        message="Order accepted and acknowledged"
    )


@router.websocket("/stream")
async def portfolio_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    portfolio_id = _get_default_portfolio()
    service = PaperPortfolioService(portfolio_id)

    try:
        while True:
            portfolio = service.get_current_state()
            if portfolio:
                await websocket.send_json({
                    "type": "portfolio_update",
                    "data": {
                        "portfolio_id": portfolio_id,
                        "cash": portfolio.get("cash", 0),
                        "equity": portfolio.get("equity", 0),
                        "buying_power": portfolio.get("buying_power", 0),
                        "positions": portfolio.get("positions", []),
                        "open_orders": portfolio.get("open_orders", []),
                        "recent_fills": portfolio.get("recent_fills", []),
                    }
                })
            import asyncio
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})