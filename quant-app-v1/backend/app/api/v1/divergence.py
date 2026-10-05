from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.database import get_connection, init_db


router = APIRouter(prefix="/divergence", tags=["divergence"])


# --- Models ---

class DivergenceAnalysisResponse(BaseModel):
    strategy_id: str
    strategy_version: int
    backtest_run_id: str
    paper_trading_id: str
    divergence_score: float
    metrics_comparison: Dict[str, Any]
    risk_factors: List[str]
    revalidation_recommended: bool
    revalidation_due: str
    created_at: str


class DivergenceAnalysesResponse(BaseModel):
    analyses: List[DivergenceAnalysisResponse]


class RevalidationReminderResponse(BaseModel):
    strategy_id: str
    strategy_name: str
    last_validation: str
    days_since_validation: int
    recommended_interval: int
    overdue: bool
    performance_drift: float


class RemindersResponse(BaseModel):
    reminders: List[RevalidationReminderResponse]


class RevalidateRequest(BaseModel):
    strategy_id: str
    force: bool = False


# --- Mock Data ---

def _generate_mock_divergences() -> List[Dict[str, Any]]:
    """Generate mock divergence analyses for demo."""
    now = datetime.now(timezone.utc)
    return [
        {
            "strategy_id": "strat_001",
            "strategy_version": 3,
            "backtest_run_id": "bt_123",
            "paper_trading_id": "pt_456",
            "divergence_score": 0.72,
            "metrics_comparison": {
                "pnl_pct": {"backtest": 15.2, "paper": 8.7, "diff": -6.5},
                "win_rate": {"backtest": 62.0, "paper": 48.0, "diff": -14.0},
                "max_drawdown": {"backtest": 8.5, "paper": 14.2, "diff": 5.7},
                "sharpe_ratio": {"backtest": 1.8, "paper": 1.1, "diff": -0.7},
                "profit_factor": {"backtest": 2.1, "paper": 1.3, "diff": -0.8},
                "avg_hold_time": {"backtest": "2d 4h", "paper": "5d 12h"},
                "total_trades": {"backtest": 45, "paper": 12},
            },
            "risk_factors": [
                "PnL divergence exceeds 5% threshold",
                "Win rate divergence exceeds 10% threshold",
                "Max drawdown exceeds 5% threshold",
                "Significant slippage not modeled in backtest",
            ],
            "revalidation_recommended": True,
            "revalidation_due": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        },
        {
            "strategy_id": "strat_002",
            "strategy_version": 1,
            "backtest_run_id": "bt_124",
            "paper_trading_id": "pt_457",
            "divergence_score": 0.18,
            "metrics_comparison": {
                "pnl_pct": {"backtest": 8.5, "paper": 7.9, "diff": -0.6},
                "win_rate": {"backtest": 58.0, "paper": 55.0, "diff": -3.0},
                "max_drawdown": {"backtest": 6.2, "paper": 7.1, "diff": 0.9},
                "sharpe_ratio": {"backtest": 1.4, "paper": 1.2, "diff": -0.2},
                "profit_factor": {"backtest": 1.6, "paper": 1.4, "diff": -0.2},
                "avg_hold_time": {"backtest": "3d 2h", "paper": "4d 1h"},
                "total_trades": {"backtest": 28, "paper": 8},
            },
            "risk_factors": [
                "Slightly longer hold times in paper trading",
            ],
            "revalidation_recommended": False,
            "revalidation_due": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "created_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        },
        {
            "strategy_id": "strat_003",
            "strategy_version": 2,
            "backtest_run_id": "bt_125",
            "paper_trading_id": "pt_458",
            "divergence_score": 0.41,
            "metrics_comparison": {
                "pnl_pct": {"backtest": 22.0, "paper": 12.0, "diff": -10.0},
                "win_rate": {"backtest": 68.0, "paper": 42.0, "diff": -26.0},
                "max_drawdown": {"backtest": 12.0, "paper": 22.0, "diff": 10.0},
                "sharpe_ratio": {"backtest": 2.1, "paper": 0.8, "diff": -1.3},
                "profit_factor": {"backtest": 2.8, "paper": 1.1, "diff": -1.7},
                "avg_hold_time": {"backtest": "1d 12h", "paper": "6d 4h"},
                "total_trades": {"backtest": 65, "paper": 18},
            },
            "risk_factors": [
                "PnL divergence exceeds 5% threshold",
                "Win rate divergence exceeds 10% threshold",
                "Max drawdown exceeds 5% threshold",
                "Sharpe ratio divergence exceeds 20% threshold",
                "Significantly longer hold times in paper",
            ],
            "revalidation_recommended": True,
            "revalidation_due": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
            "created_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
        },
    ]


def _generate_mock_reminders() -> List[Dict[str, Any]]:
    """Generate mock revalidation reminders."""
    now = datetime.now(timezone.utc)
    return [
        {
            "strategy_id": "strat_001",
            "strategy_name": "RSI Mean Reversion v3",
            "last_validation": (now - timedelta(days=45)).isoformat(),
            "days_since_validation": 45,
            "recommended_interval": 30,
            "overdue": True,
            "performance_drift": -12.5,
        },
        {
            "strategy_id": "strat_002",
            "strategy_name": "Moving Average Crossover v1",
            "last_validation": (now - timedelta(days=25)).isoformat(),
            "days_since_validation": 25,
            "recommended_interval": 60,
            "overdue": False,
            "performance_drift": -1.2,
        },
        {
            "strategy_id": "strat_003",
            "strategy_name": "Breakout Momentum v2",
            "last_validation": (now - timedelta(days=50)).isoformat(),
            "days_since_validation": 50,
            "recommended_interval": 30,
            "overdue": True,
            "performance_drift": -28.7,
        },
        {
            "strategy_id": "strat_004",
            "strategy_name": "Mean Reversion Equity v1",
            "last_validation": (now - timedelta(days=15)).isoformat(),
            "days_since_validation": 15,
            "recommended_interval": 90,
            "overdue": False,
            "performance_drift": 0.8,
        },
    ]


# --- Routes ---

router = APIRouter(prefix="/divergence", tags=["divergence"])


@router.get("/analyses", response_model=Dict[str, Any])
async def get_divergence_analyses() -> Dict[str, Any]:
    """Get all divergence analyses."""
    analyses = _generate_mock_divergences()
    return {"analyses": analyses}


@router.get("/analyses/{analysis_id}", response_model=Dict[str, Any])
async def get_divergence_analysis(analysis_id: str) -> Dict[str, Any]:
    """Get a specific divergence analysis by ID."""
    analyses = _generate_mock_divergences()
    for a in analyses:
        if a["strategy_id"] == analysis_id:
            return a
    raise HTTPException(status_code=404, detail="Analysis not found")


@router.get("/reminders", response_model=RemindersResponse)
async def get_revalidation_reminders() -> RemindersResponse:
    """Get revalidation reminders."""
    return RemindersResponse(reminders=[RevalidationReminderResponse(**r) for r in _generate_mock_reminders()])


@router.post("/revalidate/{strategy_id}")
async def trigger_revalidation(strategy_id: str, request: RevalidateRequest = RevalidateRequest(strategy_id="")) -> Dict[str, Any]:
    """Trigger a revalidation for a strategy."""
    # In real implementation, this would trigger a new backtest vs paper comparison
    return {
        "strategy_id": strategy_id,
        "status": "revalidation_triggered",
        "message": "Revalidation job queued. Results will be available shortly.",
    }