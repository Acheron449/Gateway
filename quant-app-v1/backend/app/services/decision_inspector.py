"""Slice 3.2 — DecisionInspector / paper order preview (Phase 3).
Depends on Phase 1 paper-order-preview; unimplemented.
Refs: docs/phase-3-plan.md line 15 (DecisionInspector dependency).
"""
from __future__ import annotations
from typing import Protocol, Any
from pydantic import BaseModel, Field


class PaperOrderPreview(BaseModel):
    order_id: str = Field(description="Proposed order identifier")
    instrument: str
    side: str
    quantity: float
    entry_price: float | None = None
    expected_fill_price: float | None = None
    cost_breakdown: dict[str, float] = Field(default_factory=dict)
    risk_check: str = Field(default="pending")
    approved: bool = False


class DecisionInspector(Protocol):
    def preview_order(self, order: dict[str, Any]) -> PaperOrderPreview: ...
    def inspect_paper_order(self, order_id: str) -> PaperOrderPreview: ...
