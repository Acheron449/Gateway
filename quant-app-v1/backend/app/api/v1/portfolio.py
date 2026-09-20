from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.models import OrderSide, OrderStatus, OrderType
from app.services.database import (
    create_portfolio,
    get_portfolio,
    get_portfolio_history,
)
from app.services.fill_simulator import FillSimulator, get_market_session, is_market_open
from app.services.paper_portfolio import PaperPortfolioService
from app.services.reconciliation import (
    ReconciliationService,
    AuditTrailService,
    run_eod_reconciliation,
)
from app.services.strategy_paper import StrategyPaperService, PaperVsBacktestComparator
from app.services.risk_engine import RiskCheckResult, get_risk_engine

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


DEFAULT_PORTFOLIO_ID = "paper_default"
DEFAULT_USER_ID = "default_user"

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


class FillSimulationRequest(BaseModel):
    order_id: str


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
async def simulate_fill_endpoint(order_id: str) -> FillSimulationResponse:
    portfolio_id = _get_default_portfolio()
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
async def get_market_status() -> MarketStatusResponse:
    session = get_market_session()
    return MarketStatusResponse(
        session=session.value,
        is_open=is_market_open(),
    )


@router.get("/fill-simulator/config")
async def get_fill_sim_config() -> dict:
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


class ReconciliationRequest(BaseModel):
    external_positions: dict[str, float] = Field(default_factory=dict)
    external_cash: float | None = None
    external_equity: float | None = None


class ReconciliationBreakResponse(BaseModel):
    break_type: str
    instrument: str
    internal_value: float
    external_value: float
    difference: float
    tolerance: float
    description: str


class ReconciliationResponse(BaseModel):
    portfolio_id: str
    as_of_date: str
    status: str
    breaks: list[ReconciliationBreakResponse]
    total_internal_equity: float
    total_external_equity: float
    checked_at: str


@router.post("/reconcile", response_model=ReconciliationResponse)
async def run_reconciliation(request: ReconciliationRequest) -> ReconciliationResponse:
    portfolio_id = _get_default_portfolio()
    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    external_positions = request.external_positions or {
        p["instrument_id"]: p["quantity"] for p in portfolio.get("positions", [])
    }
    external_cash = request.external_cash if request.external_cash is not None else portfolio.get("cash", 0.0)
    external_equity = request.external_equity if request.external_equity is not None else portfolio.get("equity", 0.0)

    service = ReconciliationService()
    result = service.run_full_reconciliation(
        portfolio_id,
        external_positions,
        external_cash,
        external_equity,
    )

    return ReconciliationResponse(
        portfolio_id=result.portfolio_id,
        as_of_date=result.as_of_date.isoformat(),
        status=result.status.value,
        breaks=[
            ReconciliationBreakResponse(
                break_type=b.break_type,
                instrument=b.instrument,
                internal_value=b.internal_value,
                external_value=b.external_value,
                difference=b.difference,
                tolerance=b.tolerance,
                description=b.description,
            )
            for b in result.breaks
        ],
        total_internal_equity=result.total_internal_equity,
        total_external_equity=result.total_external_equity,
        checked_at=result.checked_at.isoformat(),
    )


@router.get("/reconcile/eod", response_model=ReconciliationResponse)
async def run_eod_reconciliation_endpoint() -> ReconciliationResponse:
    portfolio_id = _get_default_portfolio()
    result = run_eod_reconciliation(portfolio_id)
    return ReconciliationResponse(
        portfolio_id=result.portfolio_id,
        as_of_date=result.as_of_date.isoformat(),
        status=result.status.value,
        breaks=[
            ReconciliationBreakResponse(
                break_type=b.break_type,
                instrument=b.instrument,
                internal_value=b.internal_value,
                external_value=b.external_value,
                difference=b.difference,
                tolerance=b.tolerance,
                description=b.description,
            )
            for b in result.breaks
        ],
        total_internal_equity=result.total_internal_equity,
        total_external_equity=result.total_external_equity,
        checked_at=result.checked_at.isoformat(),
    )


class AuditTrailFilter(BaseModel):
    start_date: str | None = None
    end_date: str | None = None
    entry_type: str | None = None


@router.post("/audit-trail")
async def get_audit_trail(filters: AuditTrailFilter) -> list[dict]:
    portfolio_id = _get_default_portfolio()
    service = AuditTrailService(portfolio_id)

    start = datetime.fromisoformat(filters.start_date).date() if filters.start_date else None
    end = datetime.fromisoformat(filters.end_date).date() if filters.end_date else None

    return service.get_audit_trail(start_date=start, end_date=end, entry_type=filters.entry_type)


@router.get("/audit-trail/trace/{fill_id}")
async def trace_fill(fill_id: str) -> dict:
    portfolio_id = _get_default_portfolio()
    service = AuditTrailService(portfolio_id)
    result = service.trace_fill_to_strategy(fill_id)
    if not result:
        raise HTTPException(status_code=404, detail="Fill not found in audit trail")
    return result


_strategy_paper_service = StrategyPaperService(_get_default_portfolio())
_comparator = PaperVsBacktestComparator(_get_default_portfolio())


class StrategyActivationRequest(BaseModel):
    strategy_id: str
    strategy_version_id: str
    config: dict | None = None


class StrategyLinkResponse(BaseModel):
    strategy_id: str
    strategy_version_id: str
    portfolio_id: str
    activated_at: str
    deactivated_at: str | None
    status: str
    config: dict


@router.post("/strategies/activate", response_model=StrategyLinkResponse)
async def activate_strategy(request: StrategyActivationRequest) -> StrategyLinkResponse:
    link = _strategy_paper_service.activate_strategy(
        request.strategy_id,
        request.strategy_version_id,
        request.config,
    )
    return StrategyLinkResponse(
        strategy_id=link.strategy_id,
        strategy_version_id=link.strategy_version_id,
        portfolio_id=link.portfolio_id,
        activated_at=link.activated_at.isoformat(),
        deactivated_at=link.deactivated_at.isoformat() if link.deactivated_at else None,
        status=link.status,
        config=link.config,
    )


@router.post("/strategies/{strategy_version_id}/deactivate", response_model=StrategyLinkResponse)
async def deactivate_strategy(strategy_version_id: str) -> StrategyLinkResponse:
    link = _strategy_paper_service.deactivate_strategy(strategy_version_id)
    if not link:
        raise HTTPException(status_code=404, detail="Strategy link not found")
    return StrategyLinkResponse(
        strategy_id=link.strategy_id,
        strategy_version_id=link.strategy_version_id,
        portfolio_id=link.portfolio_id,
        activated_at=link.activated_at.isoformat(),
        deactivated_at=link.deactivated_at.isoformat() if link.deactivated_at else None,
        status=link.status,
        config=link.config,
    )


@router.get("/strategies/active", response_model=list[StrategyLinkResponse])
async def get_active_strategies() -> list[StrategyLinkResponse]:
    links = _strategy_paper_service.get_active_strategies()
    return [
        StrategyLinkResponse(
            strategy_id=link.strategy_id,
            strategy_version_id=link.strategy_version_id,
            portfolio_id=link.portfolio_id,
            activated_at=link.activated_at.isoformat(),
            deactivated_at=link.deactivated_at.isoformat() if link.deactivated_at else None,
            status=link.status,
            config=link.config,
        )
        for link in links
    ]


class ComparisonRequest(BaseModel):
    strategy_version_id: str
    start_date: str | None = None
    end_date: str | None = None


@router.post("/strategies/compare", response_model=dict)
async def compare_paper_vs_backtest(request: ComparisonRequest) -> dict:
    from datetime import date
    start = date.fromisoformat(request.start_date) if request.start_date else None
    end = date.fromisoformat(request.end_date) if request.end_date else None

    metrics = _comparator.compare(request.strategy_version_id, start, end)
    return _comparator.generate_comparison_report(metrics)


@router.get("/strategies/{strategy_version_id}/paper-trades")
async def get_paper_trades(
    strategy_version_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    from datetime import date
    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None

    trades = _comparator.get_paper_trades(strategy_version_id, start, end)
    return [
        {
            "order_id": t.order_id,
            "fill_id": t.fill_id,
            "instrument": t.instrument,
            "side": t.side,
            "qty": t.qty,
            "price": t.price,
            "commission": t.commission,
            "timestamp": t.timestamp.isoformat(),
            "strategy_version_id": t.strategy_version_id,
        }
        for t in trades
    ]


@router.websocket("/stream")
async def portfolio_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    portfolio_id = _get_default_portfolio()
    service = PaperPortfolioService(portfolio_id)

    try:
        while True:
            for order in service.get_current_state().get("open_orders", []):
                if order["status"] in ("accepted", "partially_filled"):
                    _fill_simulator.try_fill_order(portfolio_id, order["id"])

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