"""Per-user acceptance of the simulated-results / not-advice notice (NFR-29)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.auth import CurrentUser
from app.services.database import get_notice_acceptance, record_notice_acceptance

router = APIRouter(prefix="/notices", tags=["notices"])

# Bump this when the notice wording changes so every user must acknowledge the
# new version before continuing.
CURRENT_NOTICE_VERSION = "2026-11-07"


class NoticeStatus(BaseModel):
    accepted: bool
    version: str
    accepted_at: str | None = None


@router.get("", response_model=NoticeStatus)
def read_notice(user: CurrentUser) -> NoticeStatus:
    row = get_notice_acceptance(user.id)
    accepted = bool(row) and row["version"] == CURRENT_NOTICE_VERSION
    return NoticeStatus(
        accepted=accepted,
        version=CURRENT_NOTICE_VERSION,
        accepted_at=row["accepted_at"] if accepted else None,
    )


@router.post("", response_model=NoticeStatus)
def accept_notice(user: CurrentUser) -> NoticeStatus:
    row = record_notice_acceptance(user.id, CURRENT_NOTICE_VERSION)
    return NoticeStatus(accepted=True, version=row["version"], accepted_at=row["accepted_at"])
