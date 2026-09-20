from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.database import get_connection, init_db


router = APIRouter(prefix="/risk", tags=["risk"])


# --- Models ---

class RiskMetricsResponse(BaseModel):
    portfolio_value: float
    cash: float
    equity: float
    buying_power: float
    daily_pnl: float
    daily_pnl_pct: float
    max_drawdown: float
    current_drawdown: float
    open_positions: int
    gross_exposure: float
    net_exposure: float
    concentration_risk: List[Dict[str, Any]]
    var_95: float
    var_99: float


class AlertResponse(BaseModel):
    id: str
    type: str
    message: str
    timestamp: str
    acknowledged: bool


class AlertsResponse(BaseModel):
    alerts: List[AlertResponse]


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
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS risk_alerts (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL CHECK(type IN ('info', 'warning', 'critical')),
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                acknowledged INTEGER NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_risk_alerts_ack ON risk_alerts(acknowledged)
        """)
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


def _add_alert(alert_type: str, message: str) -> str:
    alert_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO risk_alerts (id, type, message, timestamp, acknowledged) VALUES (?, ?, ?, ?, 0)",
            (alert_id, alert_type, message, now),
        )
        conn.commit()
    return alert_id


def _get_alerts() -> List[Dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        conn.row_factory = conn.execute("SELECT * FROM risk_alerts ORDER BY timestamp DESC").fetchone().__class__
        rows = conn.execute("SELECT * FROM risk_alerts ORDER BY timestamp DESC").fetchall()
    return [dict(row) for row in rows]


def _acknowledge_alert(alert_id: str) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE risk_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
        conn.commit()


# --- Mock Data Generators (for demo) ---

def _generate_mock_metrics() -> Dict[str, Any]:
    """Generate realistic mock risk metrics for demo purposes."""
    return {
        "portfolio_value": 105420.50,
        "cash": 25420.50,
        "equity": 105420.50,
        "buying_power": 105420.50,
        "daily_pnl": 1240.50,
        "daily_pnl_pct": 1.19,
        "max_drawdown": 3.2,
        "current_drawdown": 1.8,
        "open_positions": 3,
        "gross_exposure": 0.65,
        "net_exposure": 0.45,
        "concentration_risk": [
            {"symbol": "AAPL", "pct": 12.5},
            {"symbol": "MSFT", "pct": 9.8},
            {"symbol": "NVDA", "pct": 8.2},
        ],
        "var_95": 2150.00,
        "var_99": 3420.00,
    }


def _generate_mock_alerts() -> List[Dict[str, Any]]:
    """Generate mock alerts for demo."""
    now = datetime.now(timezone.utc)
    return [
        {
            "id": str(uuid4()),
            "type": "critical",
            "message": "Position AAPL exceeds 10% concentration limit (12.5%)",
            "timestamp": (now - timedelta(minutes=15)).isoformat(),
            "acknowledged": False,
        },
        {
            "id": str(uuid4()),
            "type": "warning",
            "message": "Daily P&L approaching loss limit (-4.2% of -5.0% limit)",
            "timestamp": (now - timedelta(hours=1)).isoformat(),
            "acknowledged": False,
        },
        {
            "id": str(uuid4()),
            "type": "info",
            "message": "New economic event: CPI release in 30 minutes",
            "timestamp": (now - timedelta(minutes=30)).isoformat(),
            "acknowledged": True,
        },
    ]


# --- Routes ---

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/metrics", response_model=RiskMetricsResponse)
async def get_risk_metrics() -> RiskMetricsResponse:
    """Get current portfolio risk metrics."""
    _get_risk_tables()
    return RiskMetricsResponse(**_generate_mock_metrics())


@router.get("/alerts", response_model=AlertsResponse)
async def get_risk_alerts() -> AlertsResponse:
    """Get all risk alerts."""
    _get_risk_tables()
    return AlertsResponse(alerts=[AlertResponse(**a) for a in _generate_mock_alerts()])


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str) -> Dict[str, str]:
    """Acknowledge a risk alert."""
    _get_risk_tables()
    _acknowledge_alert(alert_id)
    return {"status": "acknowledged"}


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
    
    # Create alert
    alert_type = "critical" if request.active else "info"
    message = "Kill switch ACTIVATED - All new orders blocked" if request.active else "Kill switch DEACTIVATED - Normal operation resumed"
    _add_alert(alert_type, message)
    
    return {"kill_switch_active": request.active, "message": "Kill switch updated"}