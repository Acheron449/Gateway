"""Live eligibility gates (Slice 5.2).
Requires Phase 4 paper reconciliation + authorization.
"""
from __future__ import annotations
from pydantic import BaseModel

class PaperHistoryGate(BaseModel):
    min_trades: int = 500
    min_days: int = 90

class KillSwitch(BaseModel):
    enabled: bool = False
    triggered_at: str | None = None

class LiveGates:
    def check(self, account_id: str) -> dict: ...
