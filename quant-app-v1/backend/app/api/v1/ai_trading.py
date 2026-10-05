from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import ai_trading


router = APIRouter(prefix="/ai-trading", tags=["ai-trading"])


class AiTradingConfigUpdate(BaseModel):
    """Partial update — omitted fields keep their current values."""

    enabled: Optional[bool] = None
    route: Optional[str] = Field(None, pattern="^(paper|live)$")
    symbols: Optional[List[str]] = None
    strategy: Optional[str] = Field(None, pattern="^(momentum|mean_reversion)$")
    max_position_notional: Optional[float] = Field(None, gt=0)
    confidence_threshold: Optional[float] = Field(None, ge=0, le=1)
    use_journal_memory: Optional[bool] = None
    use_backtest_memory: Optional[bool] = None
    cycle_seconds: Optional[int] = Field(None, ge=15, le=3600)


@router.get("", response_model=Dict[str, Any])
async def get_ai_trading_status() -> Dict[str, Any]:
    """Running state, config, recent decisions and learned memory."""
    return ai_trading.status()


@router.put("", response_model=Dict[str, Any])
async def update_ai_trading_config(payload: AiTradingConfigUpdate) -> Dict[str, Any]:
    """Update the AI trader configuration (saved encrypted-permission file)."""
    config = ai_trading.get_config()
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is not None:
            config[key] = value
    saved = ai_trading.save_config(config)
    return {"config": saved, "running": ai_trading.is_running()}


@router.post("/start", response_model=Dict[str, Any])
async def start_ai_trading() -> Dict[str, Any]:
    """Enable the AI trader and start its background cycle."""
    try:
        config = ai_trading.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"running": ai_trading.is_running(), "config": config}


@router.post("/stop", response_model=Dict[str, Any])
async def stop_ai_trading() -> Dict[str, Any]:
    """Stop the AI trader (config.enabled = False, loop cancelled)."""
    config = ai_trading.stop()
    return {"running": ai_trading.is_running(), "config": config}


@router.post("/cycle", response_model=Dict[str, Any])
async def run_one_cycle() -> Dict[str, Any]:
    """Evaluate every configured symbol once and act on the decisions."""
    try:
        return await ai_trading.run_cycle()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI cycle failed: {exc}") from exc


@router.get("/log", response_model=List[Dict[str, Any]])
async def get_ai_trading_log(limit: int = Query(50, ge=1, le=500)) -> List[Dict[str, Any]]:
    """Recent AI decisions with confidence and reasoning."""
    return ai_trading.recent_log(limit)


@router.get("/memory/{symbol}", response_model=Dict[str, Any])
async def get_symbol_memory(symbol: str) -> Dict[str, Any]:
    """Learned experience for one symbol (journal record + backtest edge)."""
    return {
        "symbol": symbol.upper(),
        "journal": ai_trading.journal_memory(symbol.upper()),
        "backtest_edge": ai_trading.backtest_edge(),
    }
