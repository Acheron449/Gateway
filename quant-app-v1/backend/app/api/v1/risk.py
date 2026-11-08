from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.database import get_connection, init_db


router = APIRouter(prefix="/risk", tags=["risk"])


# --- Models ---

class RiskConfigResponse(BaseModel):
    max_position_pct: float
    max_sector_pct: float
    max_gross_exposure: float
    max_drawdown_pct: float
    daily_loss_limit_pct: float
    var_limit_95: float
    kill_switch_active: bool


class RiskConfigUpdate(BaseModel):
    max_position_pct: Optional[float] = None
    max_sector_pct: Optional[float] = None
    max_gross_exposure: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    daily_loss_limit_pct: Optional[float] = None
    var_limit_95: Optional[float] = None
    kill_switch_active: Optional[bool] = None


class KillSwitchRequest(BaseModel):
    active: bool


# --- Database Helpers ---

def _get_risk_tables():
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS risk_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                max_position_pct REAL NOT NULL DEFAULT 0.10,
                max_sector_pct REAL NOT NULL DEFAULT 0.20,
                max_gross_exposure REAL NOT NULL DEFAULT 2.0,
                max_drawdown_pct REAL NOT NULL DEFAULT 0.05,
                daily_loss_limit_pct REAL NOT NULL DEFAULT 0.05,
                var_limit_95 REAL NOT NULL DEFAULT 50000.0,
                kill_switch_active INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            INSERT OR IGNORE INTO risk_config (id, updated_at) VALUES (1, ?)
        """, (datetime.now(timezone.utc).isoformat(),))
        conn.commit()


def _get_risk_config() -> Dict[str, Any]:
    init_db()
    with get_connection() as conn:
        conn.row_factory = conn.execute("SELECT * FROM risk_config WHERE id = 1").fetchone().__class__
        row = conn.execute("SELECT * FROM risk_config WHERE id = 1").fetchone()
    if not row:
        return {
            "max_position_pct": 0.10,
            "max_sector_pct": 0.20,
            "max_gross_exposure": 2.0,
            "max_drawdown_pct": 0.05,
            "daily_loss_limit_pct": 0.05,
            "var_limit_95": 50000.0,
            "kill_switch_active": False,
        }
    return {
        "max_position_pct": row["max_position_pct"],
        "max_sector_pct": row["max_sector_pct"],
        "max_gross_exposure": row["max_gross_exposure"],
        "max_drawdown_pct": row["max_drawdown_pct"],
        "daily_loss_limit_pct": row["daily_loss_limit_pct"],
        "var_limit_95": row["var_limit_95"],
        "kill_switch_active": bool(row["kill_switch_active"]),
    }


def _save_risk_config(config: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE risk_config SET 
                max_position_pct = ?, max_sector_pct = ?, max_gross_exposure = ?,
                max_drawdown_pct = ?, daily_loss_limit_pct = ?, var_limit_95 = ?,
                kill_switch_active = ?, updated_at = ?
               WHERE id = 1""",
            (config["max_position_pct"], config["max_sector_pct"], config["max_gross_exposure"],
             config["max_drawdown_pct"], config["daily_loss_limit_pct"], config["var_limit_95"],
             int(config["kill_switch_active"]), now),
        )
        conn.commit()


# --- Routes ---

@router.get("/config", response_model=RiskConfigResponse)
async def get_risk_config() -> RiskConfigResponse:
    """Get current risk configuration."""
    _get_risk_tables()
    return RiskConfigResponse(**_get_risk_config())


@router.patch("/config", response_model=RiskConfigResponse)
async def update_risk_config(request: RiskConfigUpdate) -> RiskConfigResponse:
    """Update risk configuration."""
    _get_risk_tables()
    config = _get_risk_config()
    
    update_data = request.model_dump(exclude_unset=True)
    config.update(update_data)
    
    # Validate
    if config["max_position_pct"] <= 0 or config["max_position_pct"] > 1:
        raise HTTPException(status_code=400, detail="max_position_pct must be between 0 and 1")
    if config["max_sector_pct"] <= 0 or config["max_sector_pct"] > 1:
        raise HTTPException(status_code=400, detail="max_sector_pct must be between 0 and 1")
    if config["max_gross_exposure"] <= 0:
        raise HTTPException(status_code=400, detail="max_gross_exposure must be positive")
    if config["max_drawdown_pct"] <= 0 or config["max_drawdown_pct"] > 1:
        raise HTTPException(status_code=400, detail="max_drawdown_pct must be between 0 and 1")
    if config["daily_loss_limit_pct"] <= 0 or config["daily_loss_limit_pct"] > 1:
        raise HTTPException(status_code=400, detail="daily_loss_limit_pct must be between 0 and 1")
    
    _save_risk_config(config)
    return RiskConfigResponse(**config)


@router.post("/kill-switch")
async def toggle_kill_switch(request: KillSwitchRequest) -> Dict[str, Any]:
    """Toggle kill switch."""
    _get_risk_tables()
    config = _get_risk_config()
    config["kill_switch_active"] = request.active
    _save_risk_config(config)

    return {"kill_switch_active": request.active, "message": "Kill switch updated"}