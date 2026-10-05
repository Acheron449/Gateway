from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional
from uuid import uuid4

from app.services.database import get_connection, get_portfolio


class GateStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    PENDING = "pending"
    WAIVED = "waived"


class AgreementType(str, Enum):
    LIVE_TRADING = "live_trading"
    RISK_ACKNOWLEDGEMENT = "risk_acknowledgement"
    MARKET_DATA = "market_data"
    TERMS_OF_SERVICE = "terms_of_service"


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_name: str
    status: GateStatus
    message: str
    details: dict
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class UserAgreement:
    id: str
    user_id: str
    agreement_type: AgreementType
    version: str
    content_hash: str
    signed_at: datetime
    ip_address: Optional[str]
    user_agent: Optional[str]


@dataclass(frozen=True, slots=True)
class AccountLimits:
    max_position_size: float = 10000.0
    max_daily_volume: float = 50000.0
    max_open_orders: int = 50
    max_daily_loss_pct: float = 0.03
    max_concentration_pct: float = 0.20
    allowed_symbols: list[str] = field(default_factory=list)
    blocked_symbols: list[str] = field(default_factory=list)
    trading_hours_only: bool = True


@dataclass(frozen=True, slots=True)
class LiveMonitoringData:
    account_id: str
    timestamp: datetime
    latency_ms: float
    fill_rate: float
    error_rate: float
    risk_utilization: float
    buying_power_used_pct: float
    concentration_pct: float
    daily_pnl_pct: float
    open_orders: int
    positions_count: int
    kill_switch_active: bool


def _quantize(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class PaperHistoryGate:
    """Gate: Minimum paper trading history required before live activation."""

    def __init__(
        self,
        min_trades: int = 500,
        min_days: int = 90,
    ):
        self.min_trades = min_trades
        self.min_days = min_days

    def check(self, user_id: str, portfolio_id: str = "paper_default") -> GateResult:
        portfolio = get_portfolio(portfolio_id)
        if not portfolio:
            return GateResult(
                gate_name="paper_history",
                status=GateStatus.FAILED,
                message="Paper portfolio not found",
                details={},
                checked_at=datetime.now(timezone.utc),
            )

        fills = portfolio.get("recent_fills", [])
        total_trades = len(fills)

        first_trade_date = None
        if fills:
            dates = [datetime.fromisoformat(f["timestamp"].replace("Z", "+00:00")).date() for f in fills]
            first_trade_date = min(dates)
            days_active = (date.today() - first_trade_date).days
        else:
            days_active = 0

        passed = total_trades >= self.min_trades and days_active >= self.min_days

        return GateResult(
            gate_name="paper_history",
            status=GateStatus.PASSED if passed else GateStatus.FAILED,
            message=(
                f"Paper history: {total_trades} trades over {days_active} days "
                f"(required: {self.min_trades} trades, {self.min_days} days)"
            ),
            details={
                "total_trades": total_trades,
                "days_active": days_active,
                "first_trade_date": first_trade_date.isoformat() if first_trade_date else None,
                "min_trades_required": self.min_trades,
                "min_days_required": self.min_days,
            },
            checked_at=datetime.now(timezone.utc),
        )


class AgreementGate:
    """Gate: User must sign required agreements."""

    REQUIRED_AGREEMENTS = [
        AgreementType.LIVE_TRADING,
        AgreementType.RISK_ACKNOWLEDGEMENT,
        AgreementType.TERMS_OF_SERVICE,
    ]

    def __init__(self):
        self._init_tables()

    def _init_tables(self):
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_agreements (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    agreement_type TEXT NOT NULL,
                    version TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    signed_at TEXT NOT NULL,
                    ip_address TEXT,
                    user_agent TEXT,
                    UNIQUE(user_id, agreement_type, version)
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_agreements_user_id ON user_agreements(user_id)
                """
            )
            conn.commit()

    def get_agreement_content(self, agreement_type: AgreementType, version: str) -> str:
        contents = {
            AgreementType.LIVE_TRADING: """LIVE TRADING AGREEMENT v{version}

By signing this agreement, you acknowledge and agree:

1. You understand that live trading involves real financial risk and you may lose money.
2. You have tested your strategies extensively in paper trading mode.
3. You accept full responsibility for all live trading decisions and outcomes.
4. You understand that Gateway provides execution services only, not investment advice.
5. You will comply with all applicable laws and regulations.
6. You authorize Gateway to submit orders to your designated broker on your behalf.
7. You understand that kill switches and risk controls may halt your trading at any time.
8. You have read and understood the risk disclosure document.

Signature: _________________________ Date: ______________""",
            AgreementType.RISK_ACKNOWLEDGEMENT: """RISK ACKNOWLEDGEMENT v{version}

You acknowledge the following risks of live trading:

1. MARKET RISK: Prices can move against your positions rapidly.
2. LIQUIDITY RISK: You may not be able to exit positions at desired prices.
3. EXECUTION RISK: Orders may be partially filled, rejected, or filled at worse prices.
4. TECHNICAL RISK: System failures, connectivity issues, or broker outages may occur.
5. OPERATIONAL RISK: Human error, software bugs, or configuration mistakes can cause losses.
6. REGULATORY RISK: Rule changes may affect your trading ability or costs.
7. CONCENTRATION RISK: Large positions in single instruments amplify losses.
8. LEVERAGE RISK: Margin trading can amplify both gains and losses.

You confirm you have sufficient capital to withstand potential losses.

Signature: _________________________ Date: ______________""",
            AgreementType.TERMS_OF_SERVICE: """TERMS OF SERVICE v{version}

1. SERVICE DESCRIPTION: Gateway provides algorithmic trading infrastructure.
2. USER RESPONSIBILITIES: Maintain credentials, monitor positions, comply with laws.
3. DATA: Market data provided by third parties; no warranty of accuracy.
4. LIMITATION OF LIABILITY: Gateway not liable for trading losses.
5. INDEMNIFICATION: You indemnify Gateway against claims from your use.
6. TERMINATION: Either party may terminate with notice.
7. GOVERNING LAW: Subject to applicable jurisdiction.

Signature: _________________________ Date: ______________""",
        }
        return contents.get(agreement_type, "").format(version=version)

    def get_content_hash(self, agreement_type: AgreementType, version: str) -> str:
        content = self.get_agreement_content(agreement_type, version)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def sign_agreement(
        self,
        user_id: str,
        agreement_type: AgreementType,
        version: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> UserAgreement:
        content_hash = self.get_content_hash(agreement_type, version)

        agreement = UserAgreement(
            id=str(uuid4()),
            user_id=user_id,
            agreement_type=agreement_type,
            version=version,
            content_hash=content_hash,
            signed_at=datetime.now(timezone.utc),
            ip_address=ip_address,
            user_agent=user_agent,
        )

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO user_agreements
                   (id, user_id, agreement_type, version, content_hash, signed_at, ip_address, user_agent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agreement.id,
                    agreement.user_id,
                    agreement.agreement_type.value,
                    agreement.version,
                    agreement.content_hash,
                    agreement.signed_at.isoformat(),
                    agreement.ip_address,
                    agreement.user_agent,
                ),
            )
            conn.commit()

        return agreement

    def get_user_agreements(self, user_id: str) -> list[UserAgreement]:
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            rows = conn.execute(
                "SELECT * FROM user_agreements WHERE user_id = ?",
                (user_id,),
            ).fetchall()

        return [
            UserAgreement(
                id=r["id"],
                user_id=r["user_id"],
                agreement_type=AgreementType(r["agreement_type"]),
                version=r["version"],
                content_hash=r["content_hash"],
                signed_at=datetime.fromisoformat(r["signed_at"].replace("Z", "+00:00")),
                ip_address=r.get("ip_address"),
                user_agent=r.get("user_agent"),
            )
            for r in rows
        ]

    def check(self, user_id: str) -> GateResult:
        user_agreements = self.get_user_agreements(user_id)
        signed_types = {a.agreement_type for a in user_agreements}

        missing = [a for a in self.REQUIRED_AGREEMENTS if a not in signed_types]

        if missing:
            return GateResult(
                gate_name="agreements",
                status=GateStatus.FAILED,
                message=f"Missing required agreements: {[a.value for a in missing]}",
                details={
                    "signed": [a.value for a in signed_types],
                    "missing": [a.value for a in missing],
                    "required": [a.value for a in self.REQUIRED_AGREEMENTS],
                },
                checked_at=datetime.now(timezone.utc),
            )

        return GateResult(
            gate_name="agreements",
            status=GateStatus.PASSED,
            message="All required agreements signed",
            details={
                "signed": [a.value for a in signed_types],
            },
            checked_at=datetime.now(timezone.utc),
        )

    def get_agreement_text(self, agreement_type: AgreementType, version: str = "1.0") -> str:
        return self.get_agreement_content(agreement_type, version)


class LimitsGate:
    """Gate: Account-level limits for live trading."""

    def __init__(self, limits: Optional[AccountLimits] = None):
        self.limits = limits or AccountLimits()

    def check_position_size(self, symbol: str, qty: float, price: float) -> GateResult:
        notional = qty * price
        if notional > self.limits.max_position_size:
            return GateResult(
                gate_name="position_size_limit",
                status=GateStatus.FAILED,
                message=f"Position size ${notional:,.2f} exceeds limit ${self.limits.max_position_size:,.2f}",
                details={"notional": notional, "limit": self.limits.max_position_size},
                checked_at=datetime.now(timezone.utc),
            )
        return GateResult(
            gate_name="position_size_limit",
            status=GateStatus.PASSED,
            message="Position size within limit",
            details={"notional": notional, "limit": self.limits.max_position_size},
            checked_at=datetime.now(timezone.utc),
        )

    def check_daily_volume(self, daily_volume: float) -> GateResult:
        if daily_volume > self.limits.max_daily_volume:
            return GateResult(
                gate_name="daily_volume_limit",
                status=GateStatus.FAILED,
                message=f"Daily volume ${daily_volume:,.2f} exceeds limit ${self.limits.max_daily_volume:,.2f}",
                details={"daily_volume": daily_volume, "limit": self.limits.max_daily_volume},
                checked_at=datetime.now(timezone.utc),
            )
        return GateResult(
            gate_name="daily_volume_limit",
            status=GateStatus.PASSED,
            message="Daily volume within limit",
            details={"daily_volume": daily_volume, "limit": self.limits.max_daily_volume},
            checked_at=datetime.now(timezone.utc),
        )

    def check_open_orders(self, open_orders: int) -> GateResult:
        if open_orders > self.limits.max_open_orders:
            return GateResult(
                gate_name="open_orders_limit",
                status=GateStatus.FAILED,
                message=f"Open orders {open_orders} exceeds limit {self.limits.max_open_orders}",
                details={"open_orders": open_orders, "limit": self.limits.max_open_orders},
                checked_at=datetime.now(timezone.utc),
            )
        return GateResult(
            gate_name="open_orders_limit",
            status=GateStatus.PASSED,
            message="Open orders within limit",
            details={"open_orders": open_orders, "limit": self.limits.max_open_orders},
            checked_at=datetime.now(timezone.utc),
        )

    def check_symbol_allowed(self, symbol: str) -> GateResult:
        symbol = symbol.upper()
        if self.limits.blocked_symbols and symbol in self.limits.blocked_symbols:
            return GateResult(
                gate_name="symbol_blocked",
                status=GateStatus.FAILED,
                message=f"Symbol {symbol} is blocked",
                details={"symbol": symbol},
                checked_at=datetime.now(timezone.utc),
            )
        if self.limits.allowed_symbols and symbol not in self.limits.allowed_symbols:
            return GateResult(
                gate_name="symbol_not_allowed",
                status=GateStatus.FAILED,
                message=f"Symbol {symbol} not in allowed list",
                details={"symbol": symbol, "allowed": self.limits.allowed_symbols},
                checked_at=datetime.now(timezone.utc),
            )
        return GateResult(
            gate_name="symbol_allowed",
            status=GateStatus.PASSED,
            message="Symbol allowed",
            details={"symbol": symbol},
            checked_at=datetime.now(timezone.utc),
        )

    def check_trading_hours(self) -> GateResult:
        if not self.limits.trading_hours_only:
            return GateResult(
                gate_name="trading_hours",
                status=GateStatus.PASSED,
                message="Extended hours trading allowed",
                details={},
                checked_at=datetime.now(timezone.utc),
            )

        now = datetime.now(timezone.utc)
        et = now.astimezone(timezone.utc).replace(tzinfo=None)
        hour = et.hour
        minute = et.minute
        weekday = et.weekday()

        if weekday >= 5:
            return GateResult(
                gate_name="trading_hours",
                status=GateStatus.FAILED,
                message="Market closed (weekend)",
                details={"day": et.strftime("%A")},
                checked_at=datetime.now(timezone.utc),
            )

        minutes_since_midnight = hour * 60 + minute
        if not (570 <= minutes_since_midnight < 960):
            return GateResult(
                gate_name="trading_hours",
                status=GateStatus.FAILED,
                message="Outside regular trading hours (9:30-16:00 ET)",
                details={"current_time_et": f"{hour:02d}:{minute:02d}"},
                checked_at=datetime.now(timezone.utc),
            )

        return GateResult(
            gate_name="trading_hours",
            status=GateStatus.PASSED,
            message="Within regular trading hours",
            details={"current_time_et": f"{hour:02d}:{minute:02d}"},
            checked_at=datetime.now(timezone.utc),
        )


class KillSwitch:
    """Reversible kill switch for live trading."""

    def __init__(self):
        self._active = False
        self._reason: Optional[str] = None
        self._activated_at: Optional[datetime] = None
        self._activated_by: Optional[str] = None

    def is_active(self) -> bool:
        return self._active

    def get_status(self) -> dict:
        return {
            "active": self._active,
            "reason": self._reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
            "activated_by": self._activated_by,
        }

    def activate(self, reason: str, activated_by: str = "system") -> dict:
        self._active = True
        self._reason = reason
        self._activated_at = datetime.now(timezone.utc)
        self._activated_by = activated_by
        return self.get_status()

    def deactivate(self, deactivated_by: str = "system") -> dict:
        was_active = self._active
        self._active = False
        self._reason = None
        self._activated_at = None
        self._activated_by = None
        return {"was_active": was_active, "deactivated_by": deactivated_by}

    def check(self) -> GateResult:
        if self._active:
            return GateResult(
                gate_name="kill_switch",
                status=GateStatus.FAILED,
                message=f"Kill switch active: {self._reason}",
                details=self.get_status(),
                checked_at=datetime.now(timezone.utc),
            )
        return GateResult(
            gate_name="kill_switch",
            status=GateStatus.PASSED,
            message="Kill switch inactive",
            details={},
            checked_at=datetime.now(timezone.utc),
        )


class LiveGatesService:
    """Orchestrate all live trading eligibility gates."""

    def __init__(
        self,
        paper_gate: Optional[PaperHistoryGate] = None,
        agreement_gate: Optional[AgreementGate] = None,
        limits_gate: Optional[LimitsGate] = None,
        kill_switch: Optional[KillSwitch] = None,
    ):
        self.paper_gate = paper_gate or PaperHistoryGate()
        self.agreement_gate = agreement_gate or AgreementGate()
        self.limits_gate = limits_gate or LimitsGate()
        self.kill_switch = kill_switch or KillSwitch()

    def check_all(self, user_id: str, portfolio_id: str = "paper_default") -> list[GateResult]:
        results = []
        results.append(self.paper_gate.check(user_id, portfolio_id))
        results.append(self.agreement_gate.check(user_id))
        results.append(self.kill_switch.check())
        return results

    def can_activate_live(self, user_id: str, portfolio_id: str = "paper_default") -> tuple[bool, list[GateResult]]:
        results = self.check_all(user_id, portfolio_id)
        all_passed = all(r.status == GateStatus.PASSED for r in results)
        return all_passed, results

    def check_pre_trade(
        self,
        user_id: str,
        symbol: str,
        qty: float,
        price: float,
        daily_volume: float = 0,
        open_orders: int = 0,
    ) -> list[GateResult]:
        results = []
        results.append(self.kill_switch.check())
        results.append(self.limits_gate.check_position_size(symbol, qty, price))
        results.append(self.limits_gate.check_daily_volume(daily_volume))
        results.append(self.limits_gate.check_open_orders(open_orders))
        results.append(self.limits_gate.check_symbol_allowed(symbol))
        results.append(self.limits_gate.check_trading_hours())
        return results

    def get_activation_status(self, user_id: str, portfolio_id: str = "paper_default") -> dict:
        can_activate, results = self.can_activate_live(user_id, portfolio_id)
        return {
            "can_activate": can_activate,
            "gates": [
                {
                    "gate": r.gate_name,
                    "status": r.status.value,
                    "message": r.message,
                    "details": r.details,
                }
                for r in results
            ],
            "kill_switch": self.kill_switch.get_status(),
        }


_live_gates_service: LiveGatesService | None = None


def get_live_gates() -> LiveGatesService:
    global _live_gates_service
    if _live_gates_service is None:
        _live_gates_service = LiveGatesService()
    return _live_gates_service