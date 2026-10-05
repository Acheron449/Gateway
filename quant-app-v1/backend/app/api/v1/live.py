from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.alpaca_live import (
    AlpacaLiveProvider,
    ReconciliationJob,
    LiveOrder,
    LivePosition,
    LiveAccount,
    OrderStatus,
    OrderType,
    TimeInForce,
    OrderSide,
    generate_client_order_id,
    _idempotency_store,
)
from app.services.live_gates import (
    LiveGatesService,
    AgreementGate,
    AgreementType,
    AccountLimits,
    KillSwitch,
    GateStatus,
    get_live_gates,
)
from app.services.audit_log import (
    AuditLog,
    ReplayEngine,
    AuditEvent,
    AuditEventType,
    ReplayResult,
    get_audit_log,
    get_replay_engine,
)
from app.services.production import (
    ProductionConfig,
    MonitoringConfig,
    BackupConfig,
    SecurityConfig,
    PrivacyLegalConfig,
    AlertRule,
    AlertSeverity,
    AlertChannel,
    DEFAULT_ALERT_RULES,
    generate_prometheus_rules,
    generate_grafana_dashboard,
    generate_docker_compose_monitoring,
    generate_prometheus_config,
    generate_alertmanager_config,
    generate_runbooks,
    generate_env_template,
    get_production_config,
    validate_production_readiness,
)

router = APIRouter(prefix="/live", tags=["live"])

_provider: Optional[AlpacaLiveProvider] = None
_reconciliation_job: Optional[ReconciliationJob] = None


def get_provider() -> AlpacaLiveProvider:
    global _provider
    if _provider is None:
        api_key = os.getenv("ALPACA_API_KEY") or os.getenv("ALPACA_KEY")
        api_secret = os.getenv("ALPACA_SECRET") or os.getenv("ALPACA_API_SECRET")
        base_url = os.getenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
        paper = os.getenv("ALPACA_PAPER", "false").lower() == "true"

        if not api_key or not api_secret:
            raise HTTPException(status_code=503, detail="Alpaca credentials not configured")

        _provider = AlpacaLiveProvider(api_key, api_secret, base_url, paper)
    return _provider


def get_reconciliation_job(local_get_positions, local_get_orders) -> ReconciliationJob:
    global _reconciliation_job
    if _reconciliation_job is None:
        _reconciliation_job = ReconciliationJob(
            get_provider(),
            local_get_positions,
            local_get_orders,
        )
    return _reconciliation_job


import os


class LiveOrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=12)
    qty: float = Field(gt=0)
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Optional[float] = Field(default=None, gt=0)
    stop_price: Optional[float] = Field(default=None, gt=0)
    extended_hours: bool = False
    client_order_id: Optional[str] = None


class LiveOrderResponse(BaseModel):
    id: str
    client_order_id: str
    symbol: str
    qty: float
    filled_qty: float
    filled_avg_price: Optional[float]
    order_type: str
    side: str
    time_in_force: str
    status: str
    created_at: str
    updated_at: str
    limit_price: Optional[float]
    stop_price: Optional[float]


class LiveAccountResponse(BaseModel):
    id: str
    account_number: str
    status: str
    currency: str
    cash: float
    portfolio_value: float
    equity: float
    buying_power: float
    pattern_day_trader: bool
    trading_blocked: bool
    transfers_blocked: bool
    account_blocked: bool
    multiplier: str
    long_market_value: float
    short_market_value: float
    daytrade_count: int
    reg_t_buying_power: float
    daytrading_buying_power: float


class LivePositionResponse(BaseModel):
    asset_id: str
    symbol: str
    exchange: str
    asset_class: str
    avg_entry_price: float
    qty: float
    avail_qty: float
    market_value: float
    cost_basis: float
    unrealized_pl: float
    unrealized_plpc: float
    current_price: float
    lastday_price: float
    change_today: float


class ReconciliationResponse(BaseModel):
    timestamp: str
    position_alerts: int
    equity_alerts: int
    alerts: list[dict]


@router.get("/account", response_model=LiveAccountResponse)
async def get_live_account() -> LiveAccountResponse:
    provider = get_provider()
    account = await provider.get_account()
    return LiveAccountResponse(
        id=account.id,
        account_number=account.account_number,
        status=account.status,
        currency=account.currency,
        cash=account.cash,
        portfolio_value=account.portfolio_value,
        equity=account.equity,
        buying_power=account.buying_power,
        pattern_day_trader=account.pattern_day_trader,
        trading_blocked=account.trading_blocked,
        transfers_blocked=account.transfers_blocked,
        account_blocked=account.account_blocked,
        multiplier=account.multiplier,
        long_market_value=account.long_market_value,
        short_market_value=account.short_market_value,
        daytrade_count=account.daytrade_count,
        reg_t_buying_power=account.reg_t_buying_power,
        daytrading_buying_power=account.daytrading_buying_power,
    )


@router.get("/positions", response_model=list[LivePositionResponse])
async def get_live_positions() -> list[LivePositionResponse]:
    provider = get_provider()
    positions = await provider.get_positions()
    return [
        LivePositionResponse(
            asset_id=p.asset_id,
            symbol=p.symbol,
            exchange=p.exchange,
            asset_class=p.asset_class,
            avg_entry_price=p.avg_entry_price,
            qty=p.qty,
            avail_qty=p.avail_qty,
            market_value=p.market_value,
            cost_basis=p.cost_basis,
            unrealized_pl=p.unrealized_pl,
            unrealized_plpc=p.unrealized_plpc,
            current_price=p.current_price,
            lastday_price=p.lastday_price,
            change_today=p.change_today,
        )
        for p in positions
    ]


@router.get("/positions/{symbol}", response_model=LivePositionResponse)
async def get_live_position(symbol: str) -> LivePositionResponse:
    provider = get_provider()
    position = await provider.get_position(symbol.upper())
    return LivePositionResponse(
        asset_id=position.asset_id,
        symbol=position.symbol,
        exchange=position.exchange,
        asset_class=position.asset_class,
        avg_entry_price=position.avg_entry_price,
        qty=position.qty,
        avail_qty=position.avail_qty,
        market_value=position.market_value,
        cost_basis=position.cost_basis,
        unrealized_pl=position.unrealized_pl,
        unrealized_plpc=position.unrealized_plpc,
        current_price=position.current_price,
        lastday_price=position.lastday_price,
        change_today=position.change_today,
    )


@router.post("/orders", response_model=LiveOrderResponse)
async def place_live_order(request: LiveOrderRequest) -> LiveOrderResponse:
    provider = get_provider()

    from app.services.broker_service import Order
    order = Order(
        symbol=request.symbol.upper(),
        side=request.side,
        quantity=request.qty,
        entry_price=request.limit_price or 0,
        order_type=request.order_type.value,
    )
    if request.limit_price:
        order.limit_price = request.limit_price
    if request.stop_price:
        order.stop_price = request.stop_price

    client_order_id = request.client_order_id or generate_client_order_id()
    broker_order_id = await provider.place_order(order, idempotency_key=client_order_id, extended_hours=request.extended_hours)

    if not broker_order_id:
        raise HTTPException(status_code=500, detail="Failed to place order")

    live_order = await provider.get_order(broker_order_id)
    return LiveOrderResponse(
        id=live_order.id,
        client_order_id=live_order.client_order_id,
        symbol=live_order.symbol,
        qty=live_order.qty,
        filled_qty=live_order.filled_qty,
        filled_avg_price=live_order.filled_avg_price,
        order_type=live_order.order_type.value,
        side=live_order.side.value,
        time_in_force=live_order.time_in_force.value,
        status=live_order.status.value,
        created_at=live_order.created_at.isoformat(),
        updated_at=live_order.updated_at.isoformat(),
        limit_price=live_order.limit_price,
        stop_price=live_order.stop_price,
    )


@router.get("/orders", response_model=list[LiveOrderResponse])
async def list_live_orders(
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    after: Optional[str] = None,
    until: Optional[str] = None,
    direction: str = "desc",
) -> list[LiveOrderResponse]:
    provider = get_provider()

    after_dt = datetime.fromisoformat(after.replace('Z', '+00:00')) if after else None
    until_dt = datetime.fromisoformat(until.replace('Z', '+00:00')) if until else None

    orders = await provider.list_orders(status, limit, after_dt, until_dt, direction)
    return [
        LiveOrderResponse(
            id=o.id,
            client_order_id=o.client_order_id,
            symbol=o.symbol,
            qty=o.qty,
            filled_qty=o.filled_qty,
            filled_avg_price=o.filled_avg_price,
            order_type=o.order_type.value,
            side=o.side.value,
            time_in_force=o.time_in_force.value,
            status=o.status.value,
            created_at=o.created_at.isoformat(),
            updated_at=o.updated_at.isoformat(),
            limit_price=o.limit_price,
            stop_price=o.stop_price,
        )
        for o in orders
    ]


@router.get("/orders/{order_id}", response_model=LiveOrderResponse)
async def get_live_order(order_id: str) -> LiveOrderResponse:
    provider = get_provider()
    order = await provider.get_order(order_id)
    return LiveOrderResponse(
        id=order.id,
        client_order_id=order.client_order_id,
        symbol=order.symbol,
        qty=order.qty,
        filled_qty=order.filled_qty,
        filled_avg_price=order.filled_avg_price,
        order_type=order.order_type.value,
        side=order.side.value,
        time_in_force=order.time_in_force.value,
        status=order.status.value,
        created_at=order.created_at.isoformat(),
        updated_at=order.updated_at.isoformat(),
        limit_price=order.limit_price,
        stop_price=order.stop_price,
    )


@router.delete("/orders/{order_id}")
async def cancel_live_order(order_id: str) -> dict:
    provider = get_provider()
    success = await provider.cancel_order(order_id)
    if not success:
        raise HTTPException(status_code=404, detail="Order not found or already terminal")
    return {"status": "canceled", "order_id": order_id}


@router.delete("/orders")
async def cancel_all_live_orders() -> dict:
    provider = get_provider()
    canceled = await provider.cancel_all_orders()
    return {"canceled": canceled, "count": len(canceled)}


@router.get("/activities")
async def get_live_activities(
    activity_type: str = "FILL",
    after: Optional[str] = None,
    until: Optional[str] = None,
    direction: str = "desc",
    page_size: int = Query(100, ge=1, le=1000),
) -> list[dict]:
    provider = get_provider()

    after_dt = datetime.fromisoformat(after.replace('Z', '+00:00')) if after else None
    until_dt = datetime.fromisoformat(until.replace('Z', '+00:00')) if until else None

    return await provider.get_activities(activity_type, after_dt, until_dt, direction, page_size)


@router.get("/idempotency/{key}")
async def check_idempotency(key: str) -> dict:
    entry = _idempotency_store.get(key)
    if not entry:
        return {"exists": False}
    return {
        "exists": True,
        "used": entry.used,
        "broker_order_id": entry.broker_order_id,
        "created_at": entry.created_at.isoformat(),
        "expires_at": entry.expires_at.isoformat(),
    }


def _get_paper_positions():
    from app.services.database import get_portfolio
    portfolio = get_portfolio("paper_default")
    if not portfolio:
        return []
    return portfolio.get("positions", [])


def _get_paper_orders():
    from app.services.database import get_portfolio
    portfolio = get_portfolio("paper_default")
    if not portfolio:
        return []
    return portfolio.get("open_orders", [])


@router.post("/reconcile/start")
async def start_reconciliation(interval_seconds: int = Query(300, ge=60, le=3600)) -> dict:
    global _reconciliation_job
    job = get_reconciliation_job(_get_paper_positions, _get_paper_orders)
    await job.start(interval_seconds)
    return {"status": "started", "interval_seconds": interval_seconds}


@router.post("/reconcile/stop")
async def stop_reconciliation() -> dict:
    global _reconciliation_job
    if _reconciliation_job:
        await _reconciliation_job.stop()
    return {"status": "stopped"}


@router.post("/reconcile/run", response_model=ReconciliationResponse)
async def run_reconciliation_once() -> ReconciliationResponse:
    job = get_reconciliation_job(_get_paper_positions, _get_paper_orders)
    result = await job.run_once()
    return ReconciliationResponse(**result)


@router.get("/reconcile/alerts", response_model=list[dict])
async def get_reconciliation_alerts(since: Optional[str] = None) -> list[dict]:
    job = get_reconciliation_job(_get_paper_positions, _get_paper_orders)
    since_dt = datetime.fromisoformat(since.replace('Z', '+00:00')) if since else None
    return job.get_alerts(since_dt)


@router.get("/health")
async def live_health() -> dict:
    try:
        provider = get_provider()
        account = await provider.get_account()
        return {
            "status": "healthy",
            "account_id": account.id,
            "account_status": account.status,
            "trading_blocked": account.trading_blocked,
            "rate_limit_remaining": provider._rate_limit_remaining,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


class GateResultResponse(BaseModel):
    gate_name: str
    status: str
    message: str
    details: dict
    checked_at: str


class ActivationStatusResponse(BaseModel):
    can_activate: bool
    gates: list[dict]
    kill_switch: dict


class AgreementSignRequest(BaseModel):
    agreement_type: AgreementType
    version: str = "1.0"
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class AgreementResponse(BaseModel):
    id: str
    user_id: str
    agreement_type: str
    version: str
    content_hash: str
    signed_at: str
    ip_address: Optional[str]
    user_agent: Optional[str]


class KillSwitchRequest(BaseModel):
    reason: str


@router.get("/gates/status", response_model=ActivationStatusResponse)
async def get_activation_status() -> ActivationStatusResponse:
    gates = get_live_gates()
    user_id = "default_user"
    status = gates.get_activation_status(user_id)
    return ActivationStatusResponse(**status)


@router.post("/gates/check", response_model=list[GateResultResponse])
async def check_all_gates() -> list[GateResultResponse]:
    gates = get_live_gates()
    user_id = "default_user"
    results = gates.check_all(user_id)
    return [
        GateResultResponse(
            gate_name=r.gate_name,
            status=r.status.value,
            message=r.message,
            details=r.details,
            checked_at=r.checked_at.isoformat(),
        )
        for r in results
    ]


@router.get("/agreements", response_model=list[AgreementResponse])
async def get_user_agreements() -> list[AgreementResponse]:
    gate = AgreementGate()
    user_id = "default_user"
    agreements = gate.get_user_agreements(user_id)
    return [
        AgreementResponse(
            id=a.id,
            user_id=a.user_id,
            agreement_type=a.agreement_type.value,
            version=a.version,
            content_hash=a.content_hash,
            signed_at=a.signed_at.isoformat(),
            ip_address=a.ip_address,
            user_agent=a.user_agent,
        )
        for a in agreements
    ]


@router.get("/agreements/{agreement_type}/text")
async def get_agreement_text(agreement_type: AgreementType, version: str = "1.0") -> dict:
    gate = AgreementGate()
    text = gate.get_agreement_text(agreement_type, version)
    content_hash = gate.get_content_hash(agreement_type, version)
    return {
        "agreement_type": agreement_type.value,
        "version": version,
        "content_hash": content_hash,
        "text": text,
    }


@router.post("/agreements/sign", response_model=AgreementResponse)
async def sign_agreement(request: AgreementSignRequest) -> AgreementResponse:
    gate = AgreementGate()
    user_id = "default_user"
    agreement = gate.sign_agreement(
        user_id=user_id,
        agreement_type=request.agreement_type,
        version=request.version,
        ip_address=request.ip_address,
        user_agent=request.user_agent,
    )
    return AgreementResponse(
        id=agreement.id,
        user_id=agreement.user_id,
        agreement_type=agreement.agreement_type.value,
        version=agreement.version,
        content_hash=agreement.content_hash,
        signed_at=agreement.signed_at.isoformat(),
        ip_address=agreement.ip_address,
        user_agent=agreement.user_agent,
    )


class LimitsRequest(BaseModel):
    max_position_size: Optional[float] = None
    max_daily_volume: Optional[float] = None
    max_open_orders: Optional[int] = None
    max_daily_loss_pct: Optional[float] = None
    max_concentration_pct: Optional[float] = None
    allowed_symbols: Optional[list[str]] = None
    blocked_symbols: Optional[list[str]] = None
    trading_hours_only: Optional[bool] = None


@router.get("/limits", response_model=dict)
async def get_account_limits() -> dict:
    limits = AccountLimits()
    return {
        "max_position_size": limits.max_position_size,
        "max_daily_volume": limits.max_daily_volume,
        "max_open_orders": limits.max_open_orders,
        "max_daily_loss_pct": limits.max_daily_loss_pct,
        "max_concentration_pct": limits.max_concentration_pct,
        "allowed_symbols": limits.allowed_symbols,
        "blocked_symbols": limits.blocked_symbols,
        "trading_hours_only": limits.trading_hours_only,
    }


@router.put("/limits", response_model=dict)
async def update_account_limits(request: LimitsRequest) -> dict:
    limits = AccountLimits(
        max_position_size=request.max_position_size or 10000.0,
        max_daily_volume=request.max_daily_volume or 50000.0,
        max_open_orders=request.max_open_orders or 50,
        max_daily_loss_pct=request.max_daily_loss_pct or 0.03,
        max_concentration_pct=request.max_concentration_pct or 0.20,
        allowed_symbols=request.allowed_symbols or [],
        blocked_symbols=request.blocked_symbols or [],
        trading_hours_only=request.trading_hours_only if request.trading_hours_only is not None else True,
    )
    return {
        "max_position_size": limits.max_position_size,
        "max_daily_volume": limits.max_daily_volume,
        "max_open_orders": limits.max_open_orders,
        "max_daily_loss_pct": limits.max_daily_loss_pct,
        "max_concentration_pct": limits.max_concentration_pct,
        "allowed_symbols": limits.allowed_symbols,
        "blocked_symbols": limits.blocked_symbols,
        "trading_hours_only": limits.trading_hours_only,
    }


@router.post("/kill-switch/activate")
async def activate_kill_switch(request: KillSwitchRequest) -> dict:
    gates = get_live_gates()
    return gates.kill_switch.activate(request.reason, "user")


@router.post("/kill-switch/deactivate")
async def deactivate_kill_switch() -> dict:
    gates = get_live_gates()
    return gates.kill_switch.deactivate("user")


@router.get("/kill-switch/status")
async def get_kill_switch_status() -> dict:
    gates = get_live_gates()
    return gates.kill_switch.get_status()


@router.get("/monitoring", response_model=dict)
async def get_live_monitoring() -> dict:
    try:
        provider = get_provider()
        account = await provider.get_account()
        positions = await provider.get_positions()

        total_value = sum(p.market_value for p in positions)
        cash = account.cash
        equity = account.equity

        daily_pnl = equity - account.last_equity
        daily_pnl_pct = daily_pnl / account.last_equity if account.last_equity > 0 else 0

        buying_power_used = (account.buying_power - cash) / account.buying_power if account.buying_power > 0 else 0

        max_concentration = 0.0
        if total_value > 0:
            max_concentration = max(p.market_value / total_value for p in positions) if positions else 0.0

        return {
            "account_id": account.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latency_ms": 0.0,
            "fill_rate": 1.0,
            "error_rate": 0.0,
            "risk_utilization": buying_power_used,
            "buying_power_used_pct": buying_power_used * 100,
            "concentration_pct": max_concentration * 100,
            "daily_pnl_pct": daily_pnl_pct * 100,
            "open_orders": 0,
            "positions_count": len(positions),
            "kill_switch_active": get_live_gates().kill_switch.is_active(),
            "equity": equity,
            "cash": cash,
            "buying_power": account.buying_power,
            "total_position_value": total_value,
        }
    except Exception as e:
        return {"error": str(e)}


class AuditEventResponse(BaseModel):
    event_id: str
    event_type: str
    timestamp: str
    correlation_id: str
    payload: dict
    prev_hash: str
    hash: str
    sequence: int


class ReplayRequest(BaseModel):
    start_event_id: Optional[str] = None
    end_event_id: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    event_type: Optional[str] = None
    correlation_id: Optional[str] = None
    limit: int = 1000


class ReplayResponse(BaseModel):
    start_event_id: str
    end_event_id: str
    events_replayed: int
    reconstructed_state: dict
    divergence_report: list[dict]
    hash_chain_valid: bool


class HashChainVerifyResponse(BaseModel):
    valid: bool
    errors: list[dict]


@router.post("/audit/events", response_model=list[AuditEventResponse])
async def get_audit_events(request: ReplayRequest) -> list[AuditEventResponse]:
    audit_log = get_audit_log()

    event_type = None
    if request.event_type:
        try:
            event_type = AuditEventType(request.event_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid event type: {request.event_type}")

    start_time = None
    if request.start_time:
        start_time = datetime.fromisoformat(request.start_time.replace('Z', '+00:00'))

    end_time = None
    if request.end_time:
        end_time = datetime.fromisoformat(request.end_time.replace('Z', '+00:00'))

    events = audit_log.get_events(
        start_event_id=request.start_event_id,
        end_event_id=request.end_event_id,
        start_time=start_time,
        end_time=end_time,
        event_type=event_type,
        correlation_id=request.correlation_id,
        limit=request.limit,
    )

    return [
        AuditEventResponse(
            event_id=e.event_id,
            event_type=e.event_type.value,
            timestamp=e.timestamp.isoformat(),
            correlation_id=e.correlation_id,
            payload=e.payload,
            prev_hash=e.prev_hash,
            hash=e.hash,
            sequence=e.sequence,
        )
        for e in events
    ]


@router.post("/audit/replay", response_model=ReplayResponse)
async def replay_audit_log(request: ReplayRequest) -> ReplayResponse:
    replay_engine = get_replay_engine()

    start_time = None
    if request.start_time:
        start_time = datetime.fromisoformat(request.start_time.replace('Z', '+00:00'))

    end_time = None
    if request.end_time:
        end_time = datetime.fromisoformat(request.end_time.replace('Z', '+00:00'))

    result = replay_engine.replay(
        start_event_id=request.start_event_id,
        end_event_id=request.end_event_id,
        start_time=start_time,
        end_time=end_time,
    )

    return ReplayResponse(
        start_event_id=result.start_event_id,
        end_event_id=result.end_event_id,
        events_replayed=result.events_replayed,
        reconstructed_state=result.reconstructed_state,
        divergence_report=result.divergence_report,
        hash_chain_valid=result.hash_chain_valid,
    )


@router.get("/audit/replay/order/{correlation_id}")
async def replay_order_lifecycle(correlation_id: str) -> dict:
    replay_engine = get_replay_engine()
    return replay_engine.replay_order_lifecycle(correlation_id)


@router.get("/audit/verify", response_model=HashChainVerifyResponse)
async def verify_hash_chain(
    start_sequence: int = Query(1, ge=1),
    end_sequence: Optional[int] = Query(None, ge=1),
) -> HashChainVerifyResponse:
    audit_log = get_audit_log()
    valid, errors = audit_log.verify_hash_chain(start_sequence, end_sequence)
    return HashChainVerifyResponse(valid=valid, errors=errors)


@router.get("/audit/latest-hash")
async def get_latest_hash() -> dict:
    audit_log = get_audit_log()
    hash_val = audit_log.get_latest_hash()
    return {"latest_hash": hash_val}


class ProductionConfigResponse(BaseModel):
    environment: str
    log_level: str
    debug_mode: bool
    monitoring: dict
    backup: dict
    security: dict
    privacy_legal: dict


class ValidationResponse(BaseModel):
    ready: bool
    checks: dict
    timestamp: str


@router.get("/production/config", response_model=ProductionConfigResponse)
async def get_production_config_endpoint() -> ProductionConfigResponse:
    config = get_production_config()
    return ProductionConfigResponse(
        environment=config.environment,
        log_level=config.log_level,
        debug_mode=config.debug_mode,
        monitoring={
            "prometheus_url": config.monitoring.prometheus_url,
            "grafana_url": config.monitoring.grafana_url,
            "alertmanager_url": config.monitoring.alertmanager_url,
            "scrape_interval_seconds": config.monitoring.scrape_interval_seconds,
            "evaluation_interval_seconds": config.monitoring.evaluation_interval_seconds,
            "retention_days": config.monitoring.retention_days,
        },
        backup={
            "db_pitr_enabled": config.backup.db_pitr_enabled,
            "db_backup_retention_days": config.backup.db_backup_retention_days,
            "audit_log_replication_enabled": config.backup.audit_log_replication_enabled,
            "audit_log_s3_bucket": config.backup.audit_log_s3_bucket,
            "audit_log_glacier_vault": config.backup.audit_log_glacier_vault,
            "rto_seconds": config.backup.rto_seconds,
            "rpo_seconds": config.backup.rpo_seconds,
            "backup_schedule_cron": config.backup.backup_schedule_cron,
            "verify_backups": config.backup.verify_backups,
        },
        security={
            "mtls_enabled": config.security.mtls_enabled,
            "secrets_backend": config.security.secrets_backend,
            "vault_configured": bool(config.security.vault_addr),
            "sealed_secrets_enabled": config.security.sealed_secrets_enabled,
            "dependency_scanning_enabled": config.security.dependency_scanning_enabled,
            "trivy_severity_threshold": config.security.trivy_severity_threshold,
            "dependabot_enabled": config.security.dependabot_enabled,
            "pen_test_completed": config.security.pen_test_completed,
            "pen_test_date": config.security.pen_test_date,
        },
        privacy_legal={
            "privacy_policy_url": config.privacy_legal.privacy_policy_url,
            "terms_of_service_url": config.privacy_legal.terms_of_service_url,
            "data_retention_days": config.privacy_legal.data_retention_days,
            "data_deletion_on_request": config.privacy_legal.data_deletion_on_request,
            "jurisdiction": config.privacy_legal.jurisdiction,
            "regulation_nms_compliance": config.privacy_legal.regulation_nms_compliance,
            "best_execution_docs_url": config.privacy_legal.best_execution_docs_url,
            "cookies_consent": config.privacy_legal.cookies_consent,
            "gdpr_compliance": config.privacy_legal.gdpr_compliance,
            "ccpa_compliance": config.privacy_legal.ccpa_compliance,
        },
    )


@router.get("/production/validate", response_model=ValidationResponse)
async def validate_production() -> ValidationResponse:
    result = validate_production_readiness()
    return ValidationResponse(**result)


@router.get("/production/prometheus-rules")
async def get_prometheus_rules() -> dict:
    return {"rules_yaml": generate_prometheus_rules()}


@router.get("/production/grafana-dashboard")
async def get_grafana_dashboard() -> dict:
    return generate_grafana_dashboard()


@router.get("/production/docker-compose")
async def get_docker_compose() -> dict:
    return {"docker_compose": generate_docker_compose_monitoring()}


@router.get("/production/prometheus-config")
async def get_prometheus_config() -> dict:
    return {"prometheus_yml": generate_prometheus_config()}


@router.get("/production/alertmanager-config")
async def get_alertmanager_config() -> dict:
    return {"alertmanager_yml": generate_alertmanager_config()}


@router.get("/production/runbooks")
async def get_runbooks() -> dict:
    return generate_runbooks()


@router.get("/production/env-template")
async def get_env_template() -> dict:
    return {"env_template": generate_env_template()}


@router.get("/production/alert-rules")
async def get_alert_rules() -> list[dict]:
    return [
        {
            "name": r.name,
            "condition": r.condition,
            "severity": r.severity.value,
            "channels": [c.value for c in r.channels],
            "cooldown_seconds": r.cooldown_seconds,
            "description": r.description,
        }
        for r in DEFAULT_ALERT_RULES
    ]