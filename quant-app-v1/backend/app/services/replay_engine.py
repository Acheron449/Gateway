"""Replay engine (Slice 5.3). Delegates to AuditLog.ReplayEngine."""
from __future__ import annotations
from app.services.audit_log import ReplayEngine as _ReplayEngine, get_audit_log

def get_replay_engine() -> _ReplayEngine:
    from app.services.audit_log import get_replay_engine as _get
    return _get()
