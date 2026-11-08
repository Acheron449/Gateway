"""Durable demo-trading kill switch (SRS FR-T5).

The switch lives in SQLite, not in process memory, because the UI and the
engine must read the *same* authoritative state. A restart, a second worker,
or a fresh ``RiskEngine`` instance must not silently re-enable admissions.

Every read goes to the database; there is no cached copy to go stale. If the
store cannot be reached the switch fails **closed** (treated as active), which
is the safe direction for an order gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.services.database import get_connection, init_db

SWITCH_ID = "global"
_SWITCH_COLUMNS = "id, active, reason, activated_at, activated_by, updated_at"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_state(row: Any) -> dict[str, Any]:
    return {
        "active": bool(row["active"]),
        "reason": row["reason"],
        "activated_at": row["activated_at"],
        "activated_by": row["activated_by"],
        "updated_at": row["updated_at"],
    }


def get_state() -> dict[str, Any]:
    """Current switch state, creating the idle row on first read."""
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {_SWITCH_COLUMNS} FROM kill_switch_state WHERE id = ?", (SWITCH_ID,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT OR IGNORE INTO kill_switch_state (id, active, updated_at) VALUES (?, 0, ?)",
                (SWITCH_ID, _now()),
            )
            conn.commit()
            return {
                "active": False,
                "reason": None,
                "activated_at": None,
                "activated_by": None,
                "updated_at": _now(),
            }
    return _row_to_state(row)


def is_active() -> bool:
    """True when new admissions must be blocked.

    Fails closed: an unreadable store means the engine cannot prove trading is
    allowed, so it refuses.
    """
    try:
        return bool(get_state()["active"])
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Kill switch state unreadable; refusing admissions: {}", exc)
        return True


def activate(reason: str, activated_by: str = "system") -> dict[str, Any]:
    """Block new admissions and record why."""
    init_db()
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO kill_switch_state (id, active, reason, activated_at, activated_by, updated_at)
               VALUES (?, 1, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   active = 1, reason = excluded.reason, activated_at = excluded.activated_at,
                   activated_by = excluded.activated_by, updated_at = excluded.updated_at""",
            (SWITCH_ID, reason, now, activated_by, now),
        )
        conn.commit()
    return get_state()


def reset(reset_by: str = "system") -> dict[str, Any]:
    """Clear the switch; admissions resume on the next check."""
    init_db()
    now = _now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO kill_switch_state (id, active, reason, activated_at, activated_by, updated_at)
               VALUES (?, 0, NULL, NULL, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   active = 0, reason = NULL, activated_at = NULL,
                   activated_by = excluded.activated_by, updated_at = excluded.updated_at""",
            (SWITCH_ID, reset_by, now),
        )
        conn.commit()
    return get_state()
