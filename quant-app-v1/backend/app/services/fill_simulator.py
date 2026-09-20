from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional

from app.models import Order, OrderSide, OrderType, OrderStatus
from app.services.database import get_portfolio, update_paper_order, insert_fill, insert_cash_ledger


class MarketSession(str, Enum):
    PRE_MARKET = "pre_market"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    CLOSED = "closed"


class LiquidityType(str, Enum):
    MAKER = "maker"
    TAKER = "taker"


@dataclass(frozen=True, slots=True)
class SlippageConfig:
    base_bps: float = 1.0
    volatility_multiplier: float = 5.0
    size_impact_bps_per_10k: float = 0.5
    spread_capture_pct: float = 0.5


@dataclass(frozen=True, slots=True)
class CommissionConfig:
    per_share: float = 0.005
    min_per_order: float = 1.0
    max_pct_of_trade: float = 0.01


@dataclass(frozen=True, slots=True)
class FillSimConfig:
    slippage: SlippageConfig = field(default_factory=SlippageConfig)
    commission: CommissionConfig = field(default_factory=CommissionConfig)
    partial_fill_probability: float = 0.1
    max_partial_fill_pct: float = 0.5
    min_fill_size: int = 1


def _quantize(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _quantize_price(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def get_market_session(now: Optional[datetime] = None) -> MarketSession:
    """Determine current US equity market session."""
    now = now or datetime.now(timezone.utc)
    et = now.astimezone(timezone.utc).replace(tzinfo=None)
    et_hour = et.hour
    et_minute = et.minute
    et_weekday = et.weekday()

    if et_weekday >= 5:
        return MarketSession.CLOSED

    minutes_since_midnight = et_hour * 60 + et_minute

    if 240 <= minutes_since_midnight < 570:
        return MarketSession.PRE_MARKET
    elif 570 <= minutes_since_midnight < 960:
        return MarketSession.REGULAR
    elif 960 <= minutes_since_midnight < 1140:
        return MarketSession.AFTER_HOURS
    else:
        return MarketSession.CLOSED


def is_market_open(now: Optional[datetime] = None) -> bool:
    session = get_market_session(now)
    return session in (MarketSession.PRE_MARKET, MarketSession.REGULAR, MarketSession.AFTER_HOURS)


def calculate_slippage(
    order: Order,
    bid: float,
    ask: float,
    last_price: float,
    volatility: float,
    config: SlippageConfig,
) -> tuple[float, LiquidityType]:
    """Calculate execution price with slippage. Returns (exec_price, liquidity_type)."""
    spread = ask - bid
    mid = (bid + ask) / 2

    if order.order_type == OrderType.MARKET:
        if order.side == OrderSide.BUY:
            base_slippage = spread * config.spread_capture_pct
            vol_slippage = mid * (volatility * config.volatility_multiplier / 10000)
            size_impact = mid * (order.quantity * config.size_impact_bps_per_10k / 10000)
            exec_price = ask + base_slippage + vol_slippage + size_impact
            liquidity = LiquidityType.TAKER
        else:
            base_slippage = spread * config.spread_capture_pct
            vol_slippage = mid * (volatility * config.volatility_multiplier / 10000)
            size_impact = mid * (order.quantity * config.size_impact_bps_per_10k / 10000)
            exec_price = bid - base_slippage - vol_slippage - size_impact
            liquidity = LiquidityType.TAKER

    elif order.order_type == OrderType.LIMIT:
        if order.side == OrderSide.BUY and order.limit_price and order.limit_price >= ask:
            exec_price = min(order.limit_price, ask + spread * 0.1)
            liquidity = LiquidityType.TAKER
        elif order.side == OrderSide.SELL and order.limit_price and order.limit_price <= bid:
            exec_price = max(order.limit_price, bid - spread * 0.1)
            liquidity = LiquidityType.TAKER
        elif order.side == OrderSide.BUY and order.limit_price and order.limit_price < ask:
            exec_price = order.limit_price
            liquidity = LiquidityType.MAKER
        elif order.side == OrderSide.SELL and order.limit_price and order.limit_price > bid:
            exec_price = order.limit_price
            liquidity = LiquidityType.MAKER
        else:
            exec_price = last_price
            liquidity = LiquidityType.MAKER

    else:
        exec_price = last_price
        liquidity = LiquidityType.TAKER

    return _quantize_price(exec_price), liquidity


def calculate_commission(qty: float, price: float, config: CommissionConfig) -> float:
    """Calculate commission for a fill."""
    per_share_cost = qty * config.per_share
    commission = max(per_share_cost, config.min_per_order)
    max_commission = qty * price * config.max_pct_of_trade
    return _quantize(min(commission, max_commission))


def simulate_fill(
    order: Order,
    bid: float,
    ask: float,
    last_price: float,
    volatility: float = 0.02,
    config: FillSimConfig = FillSimConfig(),
) -> Optional[dict]:
    """Simulate a fill for an order. Returns fill dict or None if no fill."""
    session = get_market_session()
    if session == MarketSession.CLOSED:
        return None

    if order.order_type == OrderType.LIMIT:
        if order.side == OrderSide.BUY and order.limit_price and order.limit_price < bid:
            return None
        if order.side == OrderSide.SELL and order.limit_price and order.limit_price > ask:
            return None

    exec_price, liquidity = calculate_slippage(order, bid, ask, last_price, volatility, config.slippage)

    fill_qty = order.quantity
    if random.random() < config.partial_fill_probability:
        max_partial = order.quantity * config.max_partial_fill_pct
        fill_qty = max(config.min_fill_size, random.uniform(config.min_fill_size, max_partial))
        fill_qty = min(fill_qty, order.quantity - order.filled_qty)

    fill_qty = min(fill_qty, order.quantity - order.filled_qty)
    if fill_qty <= 0:
        return None

    commission = calculate_commission(fill_qty, exec_price, config.commission)

    return {
        "fill_qty": fill_qty,
        "exec_price": exec_price,
        "commission": commission,
        "liquidity": liquidity.value,
        "session": session.value,
    }


class FillSimulator:
    """Service for simulating realistic order fills in paper trading."""

    def __init__(self, config: FillSimConfig = FillSimConfig()):
        self.config = config

    def get_quote_for_fill(self, instrument: str) -> tuple[float, float, float]:
        """Get bid, ask, last for fill simulation. Falls back to synthetic if no live data."""
        try:
            from app.services.market_data import get_quote
            quote = get_quote(instrument)
            if quote:
                bid = quote.bid or quote.last_price * 0.999
                ask = quote.ask or quote.last_price * 1.001
                last = quote.last_price or ((bid + ask) / 2)
                return bid, ask, last
        except Exception:
            pass

        base = 100.0 + hash(instrument) % 500
        spread = base * 0.001
        return base - spread, base + spread, base

    def try_fill_order(self, portfolio_id: str, order_id: str) -> Optional[dict]:
        """Attempt to fill an order. Returns fill info if filled, None otherwise."""
        portfolio = get_portfolio(portfolio_id)
        if not portfolio:
            return None

        open_orders = [o for o in portfolio.get("open_orders", []) if o["id"] == order_id]
        if not open_orders:
            return None

        order_data = open_orders[0]
        order = Order(
            id=order_data["id"],
            instrument=order_data["instrument_id"],
            side=OrderSide(order_data["side"]),
            order_type=OrderType(order_data["type"]),
            quantity=order_data["qty"],
            limit_price=order_data["limit_price"],
            stop_price=order_data["stop_price"],
            filled_qty=order_data.get("filled_qty", 0),
        )

        bid, ask, last = self.get_quote_for_fill(order.instrument)
        volatility = 0.02

        fill_result = simulate_fill(order, bid, ask, last, volatility, self.config)
        if not fill_result:
            return None

        from app.services.paper_portfolio import PaperPortfolioService
        service = PaperPortfolioService(portfolio_id)
        fill = service.execute_fill(
            order_id=order_id,
            instrument_id=order.instrument,
            side=order.side,
            qty=fill_result["fill_qty"],
            price=fill_result["exec_price"],
            commission=fill_result["commission"],
            liquidity=fill_result["liquidity"],
        )

        new_filled = order.filled_qty + fill_result["fill_qty"]
        new_status = OrderStatus.FILLED.value if new_filled >= order.quantity else OrderStatus.PARTIALLY_FILLED.value

        prev_avg = order_data.get("avg_fill_price") or 0
        if new_filled > 0:
            new_avg = _quantize((prev_avg * (new_filled - fill_result["fill_qty"]) + fill_result["exec_price"] * fill_result["fill_qty"]) / new_filled)
        else:
            new_avg = fill_result["exec_price"]

        update_paper_order(order_id, filled_qty=new_filled, avg_fill_price=new_avg, status=new_status)

        return {
            "fill_id": fill.id,
            "order_id": order_id,
            "instrument": order.instrument,
            "side": order.side.value,
            "qty": fill_result["fill_qty"],
            "price": fill_result["exec_price"],
            "commission": fill_result["commission"],
            "liquidity": fill_result["liquidity"],
            "session": fill_result["session"],
        }


def run_fill_simulation_loop(portfolio_id: str, interval_seconds: float = 1.0):
    """Background task to simulate fills for all open orders."""
    import time
    simulator = FillSimulator()

    while True:
        try:
            portfolio = get_portfolio(portfolio_id)
            if portfolio:
                for order in portfolio.get("open_orders", []):
                    if order["status"] in ("accepted", "partially_filled"):
                        simulator.try_fill_order(portfolio_id, order["id"])
        except Exception as e:
            print(f"Fill simulation error: {e}")

        time.sleep(interval_seconds)