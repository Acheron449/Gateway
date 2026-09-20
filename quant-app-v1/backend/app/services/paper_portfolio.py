from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any
from uuid import uuid4

from app.models import Fill, Order, OrderSide, OrderStatus, OrderType, Position, Portfolio
from app.services.database import (
    append_portfolio_event,
    create_portfolio,
    get_portfolio,
    get_portfolio_events,
    insert_cash_ledger,
    insert_fill,
    insert_paper_order,
    update_paper_order,
    update_portfolio_cash,
    update_position,
)


class EventType(str, Enum):
    ORDER_SUBMITTED = "OrderSubmitted"
    ORDER_ACKNOWLEDGED = "OrderAcknowledged"
    FILL = "Fill"
    POSITION_UPDATE = "PositionUpdate"
    CASH_UPDATE = "CashUpdate"


@dataclass(frozen=True, slots=True)
class PortfolioEvent:
    event_type: EventType
    event_data: dict[str, Any]
    timestamp: datetime


def _quantize(value: float) -> float:
    """Quantize to 2 decimal places for financial precision."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now_utc().isoformat()


class PaperPortfolioService:
    """Canonical paper portfolio with event sourcing."""

    def __init__(self, portfolio_id: str):
        self.portfolio_id = portfolio_id
        self._sequence = self._get_last_sequence()

    def _get_last_sequence(self) -> int:
        events = get_portfolio_events(self.portfolio_id)
        return max((e.get("sequence_num", 0) for e in events), default=0)

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        seq = self._next_sequence()
        append_portfolio_event(self.portfolio_id, event_type.value, data, seq)

    def apply_event(self, event: PortfolioEvent) -> None:
        """Pure function: apply a single event to rebuild portfolio state."""
        data = event.event_data
        if event.event_type == EventType.ORDER_SUBMITTED:
            pass
        elif event.event_type == EventType.ORDER_ACKNOWLEDGED:
            update_paper_order(data["order_id"], status=OrderStatus.ACCEPTED.value)
        elif event.event_type == EventType.FILL:
            self._apply_fill(data)
        elif event.event_type == EventType.POSITION_UPDATE:
            update_position(
                self.portfolio_id,
                data["instrument_id"],
                data["quantity"],
                data["avg_cost"],
                data["market_value"],
                data["unrealized_pnl"],
                data["realized_pnl"],
            )
        elif event.event_type == EventType.CASH_UPDATE:
            update_portfolio_cash(
                self.portfolio_id,
                data["cash"],
                data["equity"],
                data["buying_power"],
            )
            insert_cash_ledger(
                self.portfolio_id,
                data["amount"],
                data["type"],
                data.get("ref_id"),
                data.get("ref_type"),
            )

    def _apply_fill(self, data: dict[str, Any]) -> None:
        order_id = data["order_id"]
        instrument_id = data["instrument_id"]
        side = data["side"]
        qty = data["qty"]
        price = data["price"]
        commission = data.get("commission", 0.0)
        timestamp = data["timestamp"]
        liquidity = data.get("liquidity")

        fill_id = str(uuid4())
        insert_fill(fill_id, order_id, instrument_id, side, qty, price, commission, timestamp, liquidity)

        order = get_portfolio(self.portfolio_id)
        if not order:
            return
        open_orders = [o for o in order.get("open_orders", []) if o["id"] == order_id]
        if not open_orders:
            return
        order_data = open_orders[0]

        filled_qty = order_data.get("filled_qty", 0) + qty
        prev_avg = order_data.get("avg_fill_price") or 0
        total_filled = filled_qty
        if total_filled > 0:
            avg_fill_price = _quantize((prev_avg * (total_filled - qty) + price * qty) / total_filled)
        else:
            avg_fill_price = price

        status = OrderStatus.FILLED.value if filled_qty >= order_data["qty"] else OrderStatus.PARTIALLY_FILLED.value
        update_paper_order(order_id, filled_qty=filled_qty, avg_fill_price=avg_fill_price, status=status)

        positions = order.get("positions", [])
        pos = next((p for p in positions if p["instrument_id"] == instrument_id), None)
        if pos:
            current_qty = pos["quantity"]
            current_avg = pos["avg_cost"]
            current_realized = pos["realized_pnl"]
        else:
            current_qty = 0.0
            current_avg = 0.0
            current_realized = 0.0

        if side == OrderSide.BUY.value:
            new_qty = current_qty + qty
            if new_qty > 0:
                new_avg = _quantize((current_avg * current_qty + price * qty) / new_qty)
            else:
                new_avg = price
            realized_pnl = current_realized
        else:
            new_qty = current_qty - qty
            if current_qty > 0:
                realized_pnl = _quantize(current_realized + (price - current_avg) * qty)
            else:
                realized_pnl = current_realized
            new_avg = current_avg if new_qty > 0 else 0.0

        market_value = _quantize(new_qty * price) if new_qty != 0 else 0.0
        unrealized_pnl = 0.0

        update_position(
            self.portfolio_id,
            instrument_id,
            new_qty,
            new_avg,
            market_value,
            unrealized_pnl,
            realized_pnl,
        )

        portfolio = get_portfolio(self.portfolio_id)
        if portfolio:
            positions_list = portfolio.get("positions", [])
            total_market = sum(p.get("market_value", 0) for p in positions_list)
            total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions_list)
            total_realized = sum(p.get("realized_pnl", 0) for p in positions_list)
            cash = portfolio.get("cash", 0) - (price * qty + commission) if side == OrderSide.BUY.value else portfolio.get("cash", 0) + (price * qty - commission)
            equity = _quantize(cash + total_market)
            buying_power = equity

            update_portfolio_cash(self.portfolio_id, cash, equity, buying_power)
            insert_cash_ledger(
                self.portfolio_id,
                -(price * qty + commission) if side == OrderSide.BUY.value else (price * qty - commission),
                "fill",
                fill_id,
                "fill",
            )

    def submit_order(
        self,
        instrument_id: str,
        side: OrderSide,
        order_type: OrderType,
        qty: float,
        limit_price: float | None = None,
        stop_price: float | None = None,
        strategy_version_id: str | None = None,
    ) -> Order:
        order_id = str(uuid4())
        order = Order(
            id=order_id,
            instrument=instrument_id,
            side=side,
            order_type=order_type,
            quantity=qty,
            limit_price=limit_price,
            stop_price=stop_price,
            account_id=self.portfolio_id,
            execution_mode="paper",
            status=OrderStatus.PENDING_NEW,
            created_at=_now_utc(),
        )

        insert_paper_order(
            order_id, self.portfolio_id, strategy_version_id, instrument_id,
            side.value, order_type.value, qty, limit_price, stop_price
        )

        self._emit(EventType.ORDER_SUBMITTED, {
            "order_id": order_id,
            "instrument_id": instrument_id,
            "side": side.value,
            "type": order_type.value,
            "qty": qty,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "strategy_version_id": strategy_version_id,
        })

        return order

    def acknowledge_order(self, order_id: str) -> None:
        update_paper_order(order_id, status=OrderStatus.ACCEPTED.value)
        self._emit(EventType.ORDER_ACKNOWLEDGED, {"order_id": order_id})

    def execute_fill(
        self,
        order_id: str,
        instrument_id: str,
        side: OrderSide,
        qty: float,
        price: float,
        commission: float = 0.0,
        liquidity: str | None = None,
    ) -> Fill:
        timestamp = _iso_now()
        fill = Fill(
            id=str(uuid4()),
            order_id=order_id,
            instrument=instrument_id,
            side=side,
            quantity=qty,
            price=price,
            commission=commission,
            executed_at=_now_utc(),
            account_id=self.portfolio_id,
        )

        # Emit event and immediately apply it for real-time updates
        fill_event_data = {
            "order_id": order_id,
            "instrument_id": instrument_id,
            "side": side.value,
            "qty": qty,
            "price": price,
            "commission": commission,
            "timestamp": timestamp,
            "liquidity": liquidity,
        }
        self._emit(EventType.FILL, fill_event_data)
        self.apply_event(PortfolioEvent(EventType.FILL, fill_event_data, _now_utc()))

        return fill

    def reconstruct_portfolio(self, as_of_timestamp: str | None = None) -> Portfolio | None:
        """Rebuild portfolio state from event log up to a point in time."""
        events = get_portfolio_events(self.portfolio_id)
        if as_of_timestamp:
            cutoff = datetime.fromisoformat(as_of_timestamp.replace("Z", "+00:00"))
            events = [e for e in events if datetime.fromisoformat(e["timestamp"].replace("Z", "+00:00")) <= cutoff]

        for event_data in events:
            try:
                event = PortfolioEvent(
                    event_type=EventType(event_data["event_type"]),
                    event_data=event_data["event_data"],
                    timestamp=datetime.fromisoformat(event_data["timestamp"].replace("Z", "+00:00")),
                )
                self.apply_event(event)
            except Exception:
                continue

        return get_portfolio(self.portfolio_id)

    def get_current_state(self) -> Portfolio | None:
        """Get current portfolio state from database."""
        return get_portfolio(self.portfolio_id)

    def deposit(self, amount: float) -> None:
        """Add cash to portfolio."""
        portfolio = get_portfolio(self.portfolio_id)
        if not portfolio:
            return
        new_cash = portfolio["cash"] + amount
        new_equity = portfolio["equity"] + amount
        new_bp = portfolio["buying_power"] + amount
        update_portfolio_cash(self.portfolio_id, new_cash, new_equity, new_bp)
        insert_cash_ledger(self.portfolio_id, amount, "deposit", None, None)
        self._emit(EventType.CASH_UPDATE, {
            "cash": new_cash,
            "equity": new_equity,
            "buying_power": new_bp,
            "amount": amount,
            "type": "deposit",
            "ref_id": None,
            "ref_type": None,
        })

    def withdraw(self, amount: float) -> bool:
        """Withdraw cash from portfolio if sufficient funds."""
        portfolio = get_portfolio(self.portfolio_id)
        if not portfolio or portfolio["cash"] < amount:
            return False
        new_cash = portfolio["cash"] - amount
        new_equity = portfolio["equity"] - amount
        new_bp = portfolio["buying_power"] - amount
        update_portfolio_cash(self.portfolio_id, new_cash, new_equity, new_bp)
        insert_cash_ledger(self.portfolio_id, -amount, "withdrawal", None, None)
        self._emit(EventType.CASH_UPDATE, {
            "cash": new_cash,
            "equity": new_equity,
            "buying_power": new_bp,
            "amount": -amount,
            "type": "withdrawal",
            "ref_id": None,
            "ref_type": None,
        })
        return True