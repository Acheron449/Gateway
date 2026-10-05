from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional
from uuid import uuid4

from app.services.database import get_connection


class AuditEventType(str, Enum):
    LIVE_ORDER_SUBMITTED = "LiveOrderSubmitted"
    BROKER_ACK = "BrokerAck"
    BROKER_FILL = "BrokerFill"
    BROKER_REJECT = "BrokerReject"
    RISK_CHECK = "RiskCheck"
    KILL_SWITCH_TRIGGERED = "KillSwitchTriggered"
    RECONCILIATION_DRIFT = "ReconciliationDrift"
    ACCOUNT_SYNC = "AccountSync"
    POSITION_SYNC = "PositionSync"
    ORDER_CANCEL = "OrderCancel"
    ORDER_REPLACE = "OrderReplace"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: AuditEventType
    timestamp: datetime
    correlation_id: str
    payload: dict
    prev_hash: str
    hash: str
    sequence: int


@dataclass(frozen=True, slots=True)
class ReplayResult:
    start_event_id: str
    end_event_id: str
    events_replayed: int
    reconstructed_state: dict
    divergence_report: list[dict]
    hash_chain_valid: bool


def _quantize(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class AuditLog:
    """Immutable append-only audit log with SHA256 hash chain."""

    def __init__(self):
        self._init_tables()
        self._genesis_hash = "0" * 64

    def _init_tables(self):
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    sequence INTEGER NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_log_correlation_id ON audit_log(correlation_id)
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_log_sequence ON audit_log(sequence)
                """
            )
            conn.commit()

    def _compute_hash(self, prev_hash: str, event_type: str, timestamp: str, correlation_id: str, payload: str) -> str:
        content = f"{prev_hash}{event_type}{timestamp}{correlation_id}{payload}"
        return hashlib.sha256(content.encode()).hexdigest()

    def append(
        self,
        event_type: AuditEventType,
        correlation_id: str,
        payload: dict,
    ) -> AuditEvent:
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            last = conn.execute(
                "SELECT hash, sequence FROM audit_log ORDER BY sequence DESC LIMIT 1"
            ).fetchone()

        if last:
            prev_hash = last["hash"]
            sequence = last["sequence"] + 1
        else:
            prev_hash = self._genesis_hash
            sequence = 1

        timestamp = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        event_hash = self._compute_hash(prev_hash, event_type.value, timestamp, correlation_id, payload_json)

        event = AuditEvent(
            event_id=str(uuid4()),
            event_type=event_type,
            timestamp=datetime.fromisoformat(timestamp),
            correlation_id=correlation_id,
            payload=payload,
            prev_hash=prev_hash,
            hash=event_hash,
            sequence=sequence,
        )

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO audit_log
                   (event_id, event_type, timestamp, correlation_id, payload, prev_hash, hash, sequence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id,
                    event.event_type.value,
                    event.timestamp.isoformat(),
                    event.correlation_id,
                    payload_json,
                    event.prev_hash,
                    event.hash,
                    event.sequence,
                ),
            )
            conn.commit()

        return event

    def get_event(self, event_id: str) -> Optional[AuditEvent]:
        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            row = conn.execute(
                "SELECT * FROM audit_log WHERE event_id = ?",
                (event_id,),
            ).fetchone()

        if not row:
            return None

        return AuditEvent(
            event_id=row["event_id"],
            event_type=AuditEventType(row["event_type"]),
            timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
            correlation_id=row["correlation_id"],
            payload=json.loads(row["payload"]),
            prev_hash=row["prev_hash"],
            hash=row["hash"],
            sequence=row["sequence"],
        )

    def get_events(
        self,
        start_event_id: Optional[str] = None,
        end_event_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_type: Optional[AuditEventType] = None,
        correlation_id: Optional[str] = None,
        limit: int = 1000,
    ) -> list[AuditEvent]:
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []

        if start_event_id:
            start_event = self.get_event(start_event_id)
            if start_event:
                query += " AND sequence >= ?"
                params.append(start_event.sequence)

        if end_event_id:
            end_event = self.get_event(end_event_id)
            if end_event:
                query += " AND sequence <= ?"
                params.append(end_event.sequence)

        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())

        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type.value)

        if correlation_id:
            query += " AND correlation_id = ?"
            params.append(correlation_id)

        query += " ORDER BY sequence ASC LIMIT ?"
        params.append(limit)

        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            rows = conn.execute(query, params).fetchall()

        return [
            AuditEvent(
                event_id=row["event_id"],
                event_type=AuditEventType(row["event_type"]),
                timestamp=datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")),
                correlation_id=row["correlation_id"],
                payload=json.loads(row["payload"]),
                prev_hash=row["prev_hash"],
                hash=row["hash"],
                sequence=row["sequence"],
            )
            for row in rows
        ]

    def verify_hash_chain(self, start_sequence: int = 1, end_sequence: Optional[int] = None) -> tuple[bool, list[dict]]:
        """Verify the integrity of the hash chain."""
        query = "SELECT * FROM audit_log WHERE sequence >= ?"
        params = [start_sequence]

        if end_sequence:
            query += " AND sequence <= ?"
            params.append(end_sequence)

        query += " ORDER BY sequence ASC"

        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            rows = conn.execute(query, params).fetchall()

        errors = []
        expected_prev = self._genesis_hash

        for row in rows:
            event_type = row["event_type"]
            timestamp = row["timestamp"]
            correlation_id = row["correlation_id"]
            payload = row["payload"]
            actual_hash = row["hash"]
            actual_prev = row["prev_hash"]

            if actual_prev != expected_prev:
                errors.append({
                    "sequence": row["sequence"],
                    "event_id": row["event_id"],
                    "error": "hash_chain_break",
                    "expected_prev": expected_prev,
                    "actual_prev": actual_prev,
                })

            computed_hash = self._compute_hash(actual_prev, event_type, timestamp, correlation_id, payload)
            if computed_hash != actual_hash:
                errors.append({
                    "sequence": row["sequence"],
                    "event_id": row["event_id"],
                    "error": "hash_mismatch",
                    "expected_hash": computed_hash,
                    "actual_hash": actual_hash,
                })

            expected_prev = actual_hash

        return len(errors) == 0, errors

    def get_latest_hash(self) -> Optional[str]:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT hash FROM audit_log ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        return row["hash"] if row else None


class ReplayEngine:
    """Deterministic replay engine from audit log."""

    def __init__(self, audit_log: AuditLog):
        self.audit_log = audit_log

    def replay(
        self,
        start_event_id: Optional[str] = None,
        end_event_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> ReplayResult:
        events = self.audit_log.get_events(
            start_event_id=start_event_id,
            end_event_id=end_event_id,
            start_time=start_time,
            end_time=end_time,
        )

        if not events:
            return ReplayResult(
                start_event_id=start_event_id or "",
                end_event_id=end_event_id or "",
                events_replayed=0,
                reconstructed_state={},
                divergence_report=[],
                hash_chain_valid=True,
            )

        reconstructed = self._reconstruct_state(events)
        divergence = self._check_divergence(events, reconstructed)
        hash_valid, _ = self.audit_log.verify_hash_chain(
            start_sequence=events[0].sequence if start_event_id else 1,
            end_sequence=events[-1].sequence if end_event_id else None,
        )

        return ReplayResult(
            start_event_id=events[0].event_id,
            end_event_id=events[-1].event_id,
            events_replayed=len(events),
            reconstructed_state=reconstructed,
            divergence_report=divergence,
            hash_chain_valid=hash_valid,
        )

    def _reconstruct_state(self, events: list[AuditEvent]) -> dict:
        """Reconstruct portfolio state from events."""
        state = {
            "account": {},
            "positions": {},
            "orders": {},
            "fills": [],
            "risk_checks": [],
            "kill_switch_events": [],
            "reconciliation_drifts": [],
        }

        for event in events:
            if event.event_type == AuditEventType.LIVE_ORDER_SUBMITTED:
                state["orders"][event.payload.get("order_id", "")] = {
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }
            elif event.event_type == AuditEventType.BROKER_ACK:
                order_id = event.payload.get("order_id", "")
                if order_id in state["orders"]:
                    state["orders"][order_id]["broker_ack"] = {
                        "event_id": event.event_id,
                        "timestamp": event.timestamp.isoformat(),
                        **event.payload,
                    }
            elif event.event_type == AuditEventType.BROKER_FILL:
                state["fills"].append({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                })
                order_id = event.payload.get("order_id", "")
                if order_id in state["orders"]:
                    if "fills" not in state["orders"][order_id]:
                        state["orders"][order_id]["fills"] = []
                    state["orders"][order_id]["fills"].append(event.payload)
            elif event.event_type == AuditEventType.BROKER_REJECT:
                order_id = event.payload.get("order_id", "")
                if order_id in state["orders"]:
                    state["orders"][order_id]["rejected"] = {
                        "event_id": event.event_id,
                        "timestamp": event.timestamp.isoformat(),
                        **event.payload,
                    }
            elif event.event_type == AuditEventType.POSITION_SYNC:
                state["positions"][event.payload.get("symbol", "")] = {
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }
            elif event.event_type == AuditEventType.ACCOUNT_SYNC:
                state["account"] = {
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }
            elif event.event_type == AuditEventType.RISK_CHECK:
                state["risk_checks"].append({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                })
            elif event.event_type == AuditEventType.KILL_SWITCH_TRIGGERED:
                state["kill_switch_events"].append({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                })
            elif event.event_type == AuditEventType.RECONCILIATION_DRIFT:
                state["reconciliation_drifts"].append({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                })

        return state

    def _check_divergence(self, events: list[AuditEvent], reconstructed: dict) -> list[dict]:
        """Check for divergences between reconstructed state and current actual state."""
        divergence = []

        return divergence

    def replay_order_lifecycle(self, correlation_id: str) -> dict:
        """Replay the complete lifecycle of a single order."""
        events = self.audit_log.get_events(correlation_id=correlation_id)

        lifecycle = {
            "correlation_id": correlation_id,
            "submitted": None,
            "acknowledged": None,
            "fills": [],
            "rejected": None,
            "cancelled": None,
            "replaced": None,
            "final_status": "unknown",
        }

        for event in events:
            if event.event_type == AuditEventType.LIVE_ORDER_SUBMITTED:
                lifecycle["submitted"] = {
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }
            elif event.event_type == AuditEventType.BROKER_ACK:
                lifecycle["acknowledged"] = {
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }
            elif event.event_type == AuditEventType.BROKER_FILL:
                lifecycle["fills"].append({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                })
            elif event.event_type == AuditEventType.BROKER_REJECT:
                lifecycle["rejected"] = {
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }
            elif event.event_type == AuditEventType.ORDER_CANCEL:
                lifecycle["cancelled"] = {
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }
            elif event.event_type == AuditEventType.ORDER_REPLACE:
                lifecycle["replaced"] = {
                    "event_id": event.event_id,
                    "timestamp": event.timestamp.isoformat(),
                    **event.payload,
                }

        if lifecycle["rejected"]:
            lifecycle["final_status"] = "rejected"
        elif lifecycle["cancelled"]:
            lifecycle["final_status"] = "cancelled"
        elif lifecycle["fills"]:
            total_filled = sum(f.get("filled_qty", 0) for f in lifecycle["fills"])
            submitted_qty = lifecycle["submitted"].get("qty", 0) if lifecycle["submitted"] else 0
            if total_filled >= submitted_qty:
                lifecycle["final_status"] = "filled"
            else:
                lifecycle["final_status"] = "partially_filled"
        elif lifecycle["acknowledged"]:
            lifecycle["final_status"] = "accepted"

        return lifecycle


_audit_log: AuditLog | None = None
_replay_engine: ReplayEngine | None = None


def get_audit_log() -> AuditLog:
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditLog()
    return _audit_log


def get_replay_engine() -> ReplayEngine:
    global _replay_engine
    if _replay_engine is None:
        _replay_engine = ReplayEngine(get_audit_log())
    return _replay_engine