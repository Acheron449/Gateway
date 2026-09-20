from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any

from app.models import Order, OrderSide, OrderType, Portfolio, Position
from app.services.database import get_portfolio


class RiskCheckResult(str, Enum):
    PASSED = "passed"
    REJECTED = "rejected"
    KILL_SWITCH = "kill_switch"


@dataclass(frozen=True, slots=True)
class RiskViolation:
    check: str
    message: str
    severity: str = "error"


@dataclass
class RiskConfig:
    max_concentration_instrument: float = 0.10
    max_concentration_sector: float = 0.20
    max_concentration_asset_class: float = 0.50
    max_gross_exposure: float = 2.0
    max_net_exposure: float = 1.0
    daily_loss_limit_pct: float = 0.05
    enable_margin: bool = False
    margin_multiplier: float = 2.0
    blocked_instruments: list[str] = field(default_factory=list)
    event_blackout_minutes: int = 15

    @classmethod
    def from_env(cls) -> "RiskConfig":
        return cls(
            max_concentration_instrument=float(os.getenv("RISK_MAX_CONCENTRATION_INSTRUMENT", "0.10")),
            max_concentration_sector=float(os.getenv("RISK_MAX_CONCENTRATION_SECTOR", "0.20")),
            max_concentration_asset_class=float(os.getenv("RISK_MAX_CONCENTRATION_ASSET_CLASS", "0.50")),
            max_gross_exposure=float(os.getenv("RISK_MAX_GROSS_EXPOSURE", "2.0")),
            max_net_exposure=float(os.getenv("RISK_MAX_NET_EXPOSURE", "1.0")),
            daily_loss_limit_pct=float(os.getenv("RISK_DAILY_LOSS_LIMIT_PCT", "0.05")),
            enable_margin=os.getenv("RISK_ENABLE_MARGIN", "false").lower() == "true",
            margin_multiplier=float(os.getenv("RISK_MARGIN_MULTIPLIER", "2.0")),
            blocked_instruments=[s.strip().upper() for s in os.getenv("RISK_BLOCKED_INSTRUMENTS", "").split(",") if s.strip()],
            event_blackout_minutes=int(os.getenv("RISK_EVENT_BLACKOUT_MINUTES", "15")),
        )


class RiskEngine:
    """Server-side pre-trade risk controls. All checks run in POST /api/v1/orders before acceptance."""

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig.from_env()
        self._kill_switch_activated = False
        self._kill_switch_reason: str | None = None

    def is_kill_switch_active(self) -> bool:
        return self._kill_switch_activated

    def get_kill_switch_reason(self) -> str | None:
        return self._kill_switch_reason

    def activate_kill_switch(self, reason: str) -> None:
        self._kill_switch_activated = True
        self._kill_switch_reason = reason

    def reset_kill_switch(self) -> None:
        self._kill_switch_activated = False
        self._kill_switch_reason = None

    def _quantize(self, value: float) -> float:
        return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def check_order(self, portfolio_id: str, order: Order, current_price: float) -> tuple[RiskCheckResult, list[RiskViolation]]:
        """Run all pre-trade checks. Returns (result, violations)."""
        if self._kill_switch_activated:
            return RiskCheckResult.KILL_SWITCH, [RiskViolation("kill_switch", f"Kill switch active: {self._kill_switch_reason}")]

        portfolio = get_portfolio(portfolio_id)
        if not portfolio:
            return RiskCheckResult.REJECTED, [RiskViolation("portfolio", "Portfolio not found")]

        violations: list[RiskViolation] = []

        violations.extend(self._check_buying_power(portfolio, order, current_price))
        violations.extend(self._check_concentration(portfolio, order, current_price))
        violations.extend(self._check_exposure_limits(portfolio, order, current_price))
        violations.extend(self._check_daily_loss_limit(portfolio))
        violations.extend(self._check_instrument_restrictions(order))
        violations.extend(self._check_event_blackout())

        # If kill switch was activated during checks (e.g., daily loss limit), return KILL_SWITCH
        if self._kill_switch_activated:
            return RiskCheckResult.KILL_SWITCH, violations

        if violations:
            return RiskCheckResult.REJECTED, violations

        return RiskCheckResult.PASSED, []

    def _check_buying_power(self, portfolio: dict, order: Order, current_price: float) -> list[RiskViolation]:
        violations = []
        cash = portfolio.get("cash", 0)
        buying_power = portfolio.get("buying_power", cash)
        order_value = order.quantity * (order.limit_price or current_price)

        if order.side == OrderSide.BUY:
            if not self.config.enable_margin and order_value > cash:
                violations.append(RiskViolation(
                    "buying_power",
                    f"Insufficient cash: ${cash:,.2f} available, ${order_value:,.2f} required (margin disabled)"
                ))
            elif order_value > buying_power:
                violations.append(RiskViolation(
                    "buying_power",
                    f"Insufficient buying power: ${buying_power:,.2f} available, ${order_value:,.2f} required"
                ))

        return violations

    def _check_concentration(self, portfolio: dict, order: Order, current_price: float) -> list[RiskViolation]:
        violations = []
        positions = portfolio.get("positions", [])
        equity = portfolio.get("equity", portfolio.get("cash", 0))
        if equity <= 0:
            return violations

        order_value = order.quantity * (order.limit_price or current_price)
        instrument_exposure = 0.0

        for pos in positions:
            if pos["instrument_id"] == order.instrument:
                instrument_exposure = pos.get("market_value", 0)
                break

        if order.side == OrderSide.BUY:
            new_instrument_exposure = instrument_exposure + order_value
        else:
            new_instrument_exposure = max(0, instrument_exposure - order_value)

        instrument_pct = new_instrument_exposure / equity
        if instrument_pct > self.config.max_concentration_instrument:
            violations.append(RiskViolation(
                "concentration_instrument",
                f"Instrument concentration {instrument_pct:.1%} exceeds limit {self.config.max_concentration_instrument:.1%}"
            ))

        return violations

    def _check_exposure_limits(self, portfolio: dict, order: Order, current_price: float) -> list[RiskViolation]:
        violations = []
        positions = portfolio.get("positions", [])
        equity = portfolio.get("equity", portfolio.get("cash", 0))
        if equity <= 0:
            return violations

        long_exposure = sum(p.get("market_value", 0) for p in positions if p.get("quantity", 0) > 0)
        short_exposure = sum(abs(p.get("market_value", 0)) for p in positions if p.get("quantity", 0) < 0)

        order_value = order.quantity * (order.limit_price or current_price)
        if order.side == OrderSide.BUY:
            long_exposure += order_value
        else:
            short_exposure += order_value

        gross = long_exposure + short_exposure
        net = long_exposure - short_exposure

        gross_ratio = gross / equity
        net_ratio = abs(net) / equity

        if gross_ratio > self.config.max_gross_exposure:
            violations.append(RiskViolation(
                "gross_exposure",
                f"Gross exposure {gross_ratio:.1%} exceeds limit {self.config.max_gross_exposure:.1%}"
            ))

        if net_ratio > self.config.max_net_exposure:
            violations.append(RiskViolation(
                "net_exposure",
                f"Net exposure {net_ratio:.1%} exceeds limit {self.config.max_net_exposure:.1%}"
            ))

        return violations

    def _check_daily_loss_limit(self, portfolio: dict) -> list[RiskViolation]:
        violations = []
        equity = portfolio.get("equity", 0)
        if equity <= 0:
            return violations

        positions = portfolio.get("positions", [])
        total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)
        total_realized = sum(p.get("realized_pnl", 0) for p in positions)
        daily_pnl = total_unrealized + total_realized
        daily_pnl_pct = daily_pnl / equity

        if daily_pnl_pct <= -self.config.daily_loss_limit_pct:
            self.activate_kill_switch(f"Daily loss limit exceeded: {daily_pnl_pct:.1%} <= -{self.config.daily_loss_limit_pct:.1%}")
            violations.append(RiskViolation(
                "daily_loss_limit",
                f"Daily loss limit exceeded: {daily_pnl_pct:.1%}",
                "critical"
            ))

        return violations

    def _check_instrument_restrictions(self, order: Order) -> list[RiskViolation]:
        violations = []
        symbol = order.instrument.upper()
        if symbol in self.config.blocked_instruments:
            violations.append(RiskViolation(
                "instrument_restriction",
                f"Instrument {symbol} is on the blocklist"
            ))
        return violations

    def _check_event_blackout(self) -> list[RiskViolation]:
        violations = []
        now = datetime.now(timezone.utc)
        try:
            from app.services.calendar import get_economic_events
            events = get_economic_events()
            for event in events:
                scheduled = event.get("scheduled_at")
                if isinstance(scheduled, str):
                    scheduled = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
                if event.get("importance") == "high":
                    diff = abs((scheduled - now).total_seconds() / 60)
                    if diff <= self.config.event_blackout_minutes:
                        violations.append(RiskViolation(
                            "event_blackout",
                            f"High-impact event '{event.get('title')}' within {self.config.event_blackout_minutes} minutes"
                        ))
        except Exception:
            pass
        return violations


_risk_engine_instance: RiskEngine | None = None


def get_risk_engine() -> RiskEngine:
    global _risk_engine_instance
    if _risk_engine_instance is None:
        _risk_engine_instance = RiskEngine()
    return _risk_engine_instance