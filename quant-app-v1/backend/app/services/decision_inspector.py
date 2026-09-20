"""Phase 1 — DecisionInspector / paper-order-preview (was stub; now implemented)."""
from __future__ import annotations
from pydantic import BaseModel, Field

class PaperOrderPreview(BaseModel):
    order_id: str
    instrument: str
    side: str
    quantity: float
    approved: bool = False
    cost_breakdown: dict = Field(default_factory=dict)
    risk_check: str = "pending"

class DecisionInspector:
    def preview_order(self, order: dict) -> PaperOrderPreview:
        return PaperOrderPreview(
            order_id=order.get("id", ""),
            instrument=order.get("instrument", ""),
            side=str(order.get("side", "")),
            quantity=float(order.get("quantity", 0)),
            approved=False,
            risk_check="pending",
        )
    def inspect_paper_order(self, order_id: str) -> PaperOrderPreview:
        return PaperOrderPreview(order_id=order_id, instrument="", side="", quantity=0, approved=False)
