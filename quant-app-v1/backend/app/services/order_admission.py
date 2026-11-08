"""The single admission path for demo orders (SRS FR-T2, FR-T3, FR-R6).

Every caller — the HTTP route, the fill simulator's retries, and the bot
runner — goes through :func:`admit_order`. There is deliberately no second
write path: risk checks and the kill switch run *before* anything is
persisted, and buying power is reserved in the same transaction that inserts
the order, so two orders cannot spend the same cash.

Nothing here talks to a broker. The only output is a simulated paper order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.models import OrderSide, OrderStatus, OrderType
from app.services import kill_switch
from app.services.database import get_portfolio
from app.services.paper_portfolio import BuyingPowerUnavailable, PaperPortfolioService
from app.services.risk_engine import RiskCheckResult, get_risk_engine


class AdmissionError(Exception):
    """Raised for payload problems the caller should surface as 400."""


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    accepted: bool
    status: str
    reason: str | None
    violations: list[str] = field(default_factory=list)
    order_id: str | None = None
    price: float | None = None
    required_cash: float = 0.0
    simulated: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "status": self.status,
            "reason": self.reason,
            "violations": list(self.violations),
            "order_id": self.order_id,
            "price": self.price,
            "required_cash": self.required_cash,
            "simulated": self.simulated,
        }


def _resolve_price(instrument: str, explicit: float | None, limit_price: float | None) -> float | None:
    if explicit is not None and explicit > 0:
        return float(explicit)
    if limit_price is not None and limit_price > 0:
        return float(limit_price)
    try:
        from app.services.market_data import get_quote_triplet_sync

        quote = get_quote_triplet_sync(instrument)
    except Exception as exc:  # pragma: no cover - provider outage
        logger.warning("Quote unavailable for {} during admission: {}", instrument, exc)
        return None
    return float(quote[2]) if quote else None


def admit_order(
    *,
    portfolio_id: str,
    instrument: str,
    side: OrderSide,
    order_type: OrderType,
    qty: float,
    limit_price: float | None = None,
    stop_price: float | None = None,
    strategy_version_id: str | None = None,
    price: float | None = None,
    source: str = "api",
) -> AdmissionDecision:
    """Run the gate, reserve cash, then persist the order.

    ``source`` is recorded for auditability only; it carries no privileges —
    a bot is subject to exactly the same checks as a human request.
    """
    symbol = (instrument or "").strip().upper()
    if not symbol:
        raise AdmissionError("instrument is required")
    if qty is None or qty <= 0:
        raise AdmissionError("quantity must be greater than zero")

    if kill_switch.is_active():
        state = kill_switch.get_state()
        reason = state.get("reason") or "kill switch active"
        return AdmissionDecision(
            accepted=False,
            status="blocked",
            reason=f"Kill switch active: {reason}",
        )

    portfolio = get_portfolio(portfolio_id)
    if portfolio is None:
        return AdmissionDecision(accepted=False, status="rejected", reason="Portfolio not found")

    resolved_price = _resolve_price(symbol, price, limit_price)
    if resolved_price is None:
        return AdmissionDecision(
            accepted=False,
            status="unavailable",
            reason="Market data is unavailable; supply a limit price or configure a quote provider",
        )

    from app.models import Order

    order = Order(
        id="",
        instrument=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        limit_price=limit_price,
        stop_price=stop_price,
        account_id=portfolio_id,
        execution_mode="paper",
        status=OrderStatus.PENDING_NEW,
    )

    risk_engine = get_risk_engine()
    verdict, violations = risk_engine.check_order(portfolio_id, order, resolved_price)
    if verdict == RiskCheckResult.KILL_SWITCH:
        messages = [v.message for v in violations] or ["Kill switch active"]
        return AdmissionDecision(
            accepted=False,
            status="blocked",
            reason=messages[0],
            violations=messages,
            price=resolved_price,
        )
    if verdict == RiskCheckResult.REJECTED:
        messages = [v.message for v in violations]
        return AdmissionDecision(
            accepted=False,
            status="rejected",
            reason="; ".join(messages),
            violations=messages,
            price=resolved_price,
        )

    required_cash = round(qty * resolved_price, 2) if side == OrderSide.BUY else 0.0

    service = PaperPortfolioService(portfolio_id)
    try:
        submitted = service.submit_order(
            instrument_id=symbol,
            side=side,
            order_type=order_type,
            qty=qty,
            limit_price=limit_price,
            stop_price=stop_price,
            strategy_version_id=strategy_version_id,
            required_cash=required_cash,
        )
    except BuyingPowerUnavailable as exc:
        return AdmissionDecision(
            accepted=False,
            status="rejected",
            reason=str(exc),
            violations=["buying_power"],
            price=resolved_price,
            required_cash=required_cash,
        )

    service.acknowledge_order(submitted.id)
    return AdmissionDecision(
        accepted=True,
        status="accepted",
        reason=None,
        order_id=submitted.id,
        price=resolved_price,
        required_cash=required_cash,
    )
