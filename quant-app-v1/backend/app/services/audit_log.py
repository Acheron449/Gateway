"""Event-sourced audit log (Slice 5.3). Deterministic replay requires audit chain."""
from __future__ import annotations

class AuditEvent:
    event_id: str
    timestamp: str
    correlation_id: str
    event_type: str
    payload_json: str
    hash_chain: str  # SHA256(prev_hash + current)

class ReplayEngine:
    def replay(self, start: str, end: str) -> dict: ...
