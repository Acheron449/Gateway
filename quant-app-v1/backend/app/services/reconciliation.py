from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional
from uuid import uuid4

from app.services.database import (
    get_portfolio,
    get_portfolio_history,
    append_portfolio_event,
)
from app.models import OrderSide


class ReconciliationStatus(str, Enum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    MISSING_INTERNAL = "missing_internal"
    MISSING_EXTERNAL = "missing_external"


@dataclass(frozen=True, slots=True)
class ReconciliationBreak:
    break_type: str
    instrument: str
    internal_value: float
    external_value: float
    difference: float
    tolerance: float
    description: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    portfolio_id: str
    as_of_date: date
    status: ReconciliationStatus
    breaks: list[ReconciliationBreak]
    total_internal_equity: float
    total_external_equity: float
    checked_at: datetime


@dataclass(frozen=True, slots=True)
class JournalEntry:
    id: str
    portfolio_id: str
    entry_type: str
    description: str
    debit_account: str
    credit_account: str
    amount: float
    ref_id: Optional[str]
    ref_type: Optional[str]
    strategy_version_id: Optional[str]
    data_snapshot_id: Optional[str]
    risk_decision_id: Optional[str]
    created_at: datetime


def _quantize(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _compute_hash(data: dict) -> str:
    content = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class ReconciliationService:
    """End-of-day reconciliation between internal state and external sources."""

    def __init__(self, position_tolerance_bps: float = 5.0, cash_tolerance: float = 0.01):
        self.position_tolerance_bps = position_tolerance_bps
        self.cash_tolerance = cash_tolerance

    def reconcile_positions(
        self,
        portfolio_id: str,
        external_positions: dict[str, float],
        as_of: Optional[datetime] = None,
    ) -> list[ReconciliationBreak]:
        """Compare internal positions with external (broker/custodian) positions."""
        portfolio = get_portfolio(portfolio_id)
        if not portfolio:
            return [ReconciliationBreak(
                break_type="portfolio_not_found",
                instrument="",
                internal_value=0,
                external_value=0,
                difference=0,
                tolerance=0,
                description=f"Portfolio {portfolio_id} not found",
            )]

        internal_positions = {
            p["instrument_id"]: p["quantity"]
            for p in portfolio.get("positions", [])
            if p.get("quantity", 0) != 0
        }

        all_instruments = set(internal_positions.keys()) | set(external_positions.keys())
        breaks = []

        for instrument in all_instruments:
            internal_qty = internal_positions.get(instrument, 0.0)
            external_qty = external_positions.get(instrument, 0.0)

            if internal_qty == external_qty:
                continue

            diff = abs(internal_qty - external_qty)
            tolerance = max(1.0, abs(external_qty) * self.position_tolerance_bps / 10000)

            if diff <= tolerance:
                continue

            if instrument not in internal_positions:
                break_type = ReconciliationStatus.MISSING_INTERNAL
            elif instrument not in external_positions:
                break_type = ReconciliationStatus.MISSING_EXTERNAL
            else:
                break_type = ReconciliationStatus.MISMATCH

            breaks.append(ReconciliationBreak(
                break_type=break_type.value,
                instrument=instrument,
                internal_value=internal_qty,
                external_value=external_qty,
                difference=internal_qty - external_qty,
                tolerance=tolerance,
                description=f"Position mismatch for {instrument}: internal={internal_qty}, external={external_qty}",
            ))

        return breaks

    def reconcile_cash(
        self,
        portfolio_id: str,
        external_cash: float,
        as_of: Optional[datetime] = None,
    ) -> list[ReconciliationBreak]:
        """Compare internal cash with external cash balance."""
        portfolio = get_portfolio(portfolio_id)
        if not portfolio:
            return [ReconciliationBreak(
                break_type="portfolio_not_found",
                instrument="CASH",
                internal_value=0,
                external_value=external_cash,
                difference=-external_cash,
                tolerance=self.cash_tolerance,
                description=f"Portfolio {portfolio_id} not found",
            )]

        internal_cash = portfolio.get("cash", 0.0)
        diff = internal_cash - external_cash

        if abs(diff) <= self.cash_tolerance:
            return []

        return [ReconciliationBreak(
            break_type=ReconciliationStatus.MISMATCH.value,
            instrument="CASH",
            internal_value=internal_cash,
            external_value=external_cash,
            difference=diff,
            tolerance=self.cash_tolerance,
            description=f"Cash mismatch: internal={internal_cash}, external={external_cash}",
        )]

    def reconcile_equity(
        self,
        portfolio_id: str,
        external_equity: float,
        as_of: Optional[datetime] = None,
    ) -> list[ReconciliationBreak]:
        """Compare total equity."""
        portfolio = get_portfolio(portfolio_id)
        if not portfolio:
            return [ReconciliationBreak(
                break_type="portfolio_not_found",
                instrument="EQUITY",
                internal_value=0,
                external_value=external_equity,
                difference=-external_equity,
                tolerance=external_equity * 0.001,
                description=f"Portfolio {portfolio_id} not found",
            )]

        internal_equity = portfolio.get("equity", 0.0)
        diff = internal_equity - external_equity
        tolerance = external_equity * 0.001

        if abs(diff) <= tolerance:
            return []

        return [ReconciliationBreak(
            break_type=ReconciliationStatus.MISMATCH.value,
            instrument="EQUITY",
            internal_value=internal_equity,
            external_value=external_equity,
            difference=diff,
            tolerance=tolerance,
            description=f"Equity mismatch: internal={internal_equity}, external={external_equity}",
        )]

    def run_full_reconciliation(
        self,
        portfolio_id: str,
        external_positions: dict[str, float],
        external_cash: float,
        external_equity: float,
        as_of: Optional[datetime] = None,
    ) -> ReconciliationResult:
        """Run complete EOD reconciliation."""
        as_of = as_of or datetime.now(timezone.utc)
        as_of_date = as_of.date()

        all_breaks = []
        all_breaks.extend(self.reconcile_positions(portfolio_id, external_positions, as_of))
        all_breaks.extend(self.reconcile_cash(portfolio_id, external_cash, as_of))
        all_breaks.extend(self.reconcile_equity(portfolio_id, external_equity, as_of))

        portfolio = get_portfolio(portfolio_id)
        internal_equity = portfolio.get("equity", 0.0) if portfolio else 0.0

        status = ReconciliationStatus.MATCHED if not all_breaks else ReconciliationStatus.MISMATCH

        return ReconciliationResult(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            status=status,
            breaks=all_breaks,
            total_internal_equity=internal_equity,
            total_external_equity=external_equity,
            checked_at=as_of,
        )

    def generate_reconciliation_report(self, result: ReconciliationResult) -> dict:
        """Generate structured reconciliation report."""
        return {
            "portfolio_id": result.portfolio_id,
            "as_of_date": result.as_of_date.isoformat(),
            "status": result.status.value,
            "checked_at": result.checked_at.isoformat(),
            "summary": {
                "total_breaks": len(result.breaks),
                "internal_equity": result.total_internal_equity,
                "external_equity": result.total_external_equity,
                "equity_difference": result.total_internal_equity - result.total_external_equity,
            },
            "breaks": [
                {
                    "break_type": b.break_type,
                    "instrument": b.instrument,
                    "internal_value": b.internal_value,
                    "external_value": b.external_value,
                    "difference": b.difference,
                    "tolerance": b.tolerance,
                    "description": b.description,
                }
                for b in result.breaks
            ],
        }


class AuditTrailService:
    """Immutable audit trail linking fills → orders → strategy → data → risk decisions."""

    def __init__(self, portfolio_id: str):
        self.portfolio_id = portfolio_id

    def create_journal_entry(
        self,
        entry_type: str,
        description: str,
        debit_account: str,
        credit_account: str,
        amount: float,
        ref_id: Optional[str] = None,
        ref_type: Optional[str] = None,
        strategy_version_id: Optional[str] = None,
        data_snapshot_id: Optional[str] = None,
        risk_decision_id: Optional[str] = None,
    ) -> JournalEntry:
        """Create an immutable journal entry with full traceability."""
        entry = JournalEntry(
            id=str(uuid4()),
            portfolio_id=self.portfolio_id,
            entry_type=entry_type,
            description=description,
            debit_account=debit_account,
            credit_account=credit_account,
            amount=_quantize(amount),
            ref_id=ref_id,
            ref_type=ref_type,
            strategy_version_id=strategy_version_id,
            data_snapshot_id=data_snapshot_id,
            risk_decision_id=risk_decision_id,
            created_at=datetime.now(timezone.utc),
        )

        event_data = {
            "journal_entry_id": entry.id,
            "entry_type": entry_type,
            "description": description,
            "debit_account": debit_account,
            "credit_account": credit_account,
            "amount": entry.amount,
            "ref_id": ref_id,
            "ref_type": ref_type,
            "strategy_version_id": strategy_version_id,
            "data_snapshot_id": data_snapshot_id,
            "risk_decision_id": risk_decision_id,
        }

        append_portfolio_event(self.portfolio_id, "JournalEntry", event_data, 0)

        return entry

    def record_fill_journal(
        self,
        fill_id: str,
        order_id: str,
        instrument: str,
        side: OrderSide,
        qty: float,
        price: float,
        commission: float,
        strategy_version_id: Optional[str] = None,
        data_snapshot_id: Optional[str] = None,
        risk_decision_id: Optional[str] = None,
    ) -> list[JournalEntry]:
        """Create journal entries for a fill (double-entry bookkeeping)."""
        entries = []

        trade_value = qty * price
        total_cost = trade_value + commission

        if side == OrderSide.BUY:
            entries.append(self.create_journal_entry(
                entry_type="fill_cash",
                description=f"Buy {qty} {instrument} @ {price}",
                debit_account=f"Position:{instrument}",
                credit_account="Cash:Broker",
                amount=total_cost,
                ref_id=fill_id,
                ref_type="fill",
                strategy_version_id=strategy_version_id,
                data_snapshot_id=data_snapshot_id,
                risk_decision_id=risk_decision_id,
            ))

            entries.append(self.create_journal_entry(
                entry_type="fill_commission",
                description=f"Commission for buy {qty} {instrument}",
                debit_account="Expense:Commission",
                credit_account="Cash:Broker",
                amount=commission,
                ref_id=fill_id,
                ref_type="fill",
                strategy_version_id=strategy_version_id,
                data_snapshot_id=data_snapshot_id,
                risk_decision_id=risk_decision_id,
            ))
        else:
            entries.append(self.create_journal_entry(
                entry_type="fill_cash",
                description=f"Sell {qty} {instrument} @ {price}",
                debit_account="Cash:Broker",
                credit_account=f"Position:{instrument}",
                amount=trade_value - commission,
                ref_id=fill_id,
                ref_type="fill",
                strategy_version_id=strategy_version_id,
                data_snapshot_id=data_snapshot_id,
                risk_decision_id=risk_decision_id,
            ))

            entries.append(self.create_journal_entry(
                entry_type="fill_commission",
                description=f"Commission for sell {qty} {instrument}",
                debit_account="Expense:Commission",
                credit_account="Cash:Broker",
                amount=commission,
                ref_id=fill_id,
                ref_type="fill",
                strategy_version_id=strategy_version_id,
                data_snapshot_id=data_snapshot_id,
                risk_decision_id=risk_decision_id,
            ))

        return entries

    def record_risk_decision(
        self,
        order_id: str,
        decision: str,
        checks_passed: list[str],
        checks_failed: list[str],
        risk_params: dict,
    ) -> JournalEntry:
        """Record a risk engine decision for audit trail."""
        return self.create_journal_entry(
            entry_type="risk_decision",
            description=f"Risk check {decision} for order {order_id}",
            debit_account="Audit:RiskDecision",
            credit_account="Audit:RiskDecision",
            amount=0.0,
            ref_id=order_id,
            ref_type="order",
            risk_decision_id=f"risk_{order_id}",
            data_snapshot_id=None,
            strategy_version_id=None,
        )

    def get_audit_trail(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        entry_type: Optional[str] = None,
    ) -> list[dict]:
        """Query audit trail with filters."""
        from app.services.database import get_portfolio_events

        events = get_portfolio_events(self.portfolio_id)
        filtered = []

        for event in events:
            if event.get("event_type") != "JournalEntry":
                continue

            data = event.get("event_data", {})
            created = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))

            if start_date and created.date() < start_date:
                continue
            if end_date and created.date() > end_date:
                continue
            if entry_type and data.get("entry_type") != entry_type:
                continue

            filtered.append(data)

        return filtered

    def trace_fill_to_strategy(self, fill_id: str) -> Optional[dict]:
        """Trace a fill back to its originating strategy version and data snapshot."""
        trail = self.get_audit_trail()
        for entry in trail:
            if entry.get("ref_id") == fill_id and entry.get("ref_type") == "fill":
                return {
                    "fill_id": fill_id,
                    "strategy_version_id": entry.get("strategy_version_id"),
                    "data_snapshot_id": entry.get("data_snapshot_id"),
                    "risk_decision_id": entry.get("risk_decision_id"),
                    "entry": entry,
                }
        return None


def run_eod_reconciliation(portfolio_id: str) -> ReconciliationResult:
    """Convenience function to run EOD reconciliation with synthetic external data."""
    service = ReconciliationService()
    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    external_positions = {p["instrument_id"]: p["quantity"] for p in portfolio.get("positions", [])}
    external_cash = portfolio.get("cash", 0.0)
    external_equity = portfolio.get("equity", 0.0)

    return service.run_full_reconciliation(
        portfolio_id,
        external_positions,
        external_cash,
        external_equity,
    )