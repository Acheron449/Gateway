from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.services import ai_trading


router = APIRouter(prefix="/ai-trading", tags=["ai-trading"])


class AiTradingConfigUpdate(BaseModel):
    """Partial update — omitted fields keep their current values."""

    enabled: Optional[bool] = None
    route: Optional[str] = Field(None, pattern="^paper$")
    symbols: Optional[List[str]] = None
    strategy: Optional[str] = Field(None, pattern="^(momentum|mean_reversion)$")
    max_position_notional: Optional[float] = Field(None, gt=0)
    confidence_threshold: Optional[float] = Field(None, ge=0, le=1)
    use_journal_memory: Optional[bool] = None
    use_backtest_memory: Optional[bool] = None
    cycle_seconds: Optional[int] = Field(None, ge=15, le=3600)


@router.get("", response_model=Dict[str, Any])
async def get_ai_trading_status(user: CurrentUser) -> Dict[str, Any]:
    """Running state, config, recent decisions and learned memory for the caller."""
    return ai_trading.status(user.id)


@router.put("", response_model=Dict[str, Any])
async def update_ai_trading_config(
    payload: AiTradingConfigUpdate, user: CurrentUser
) -> Dict[str, Any]:
    """Update this account's AI trader configuration."""
    config = ai_trading.get_config(user.id)
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if value is not None:
            config[key] = value
    saved = ai_trading.save_config(user.id, config)
    return {"config": saved, "running": ai_trading.is_running(user.id)}


@router.post("/start", response_model=Dict[str, Any])
async def start_ai_trading(user: CurrentUser) -> Dict[str, Any]:
    """Enable this account's AI trader and start its background cycle."""
    try:
        config = ai_trading.start(user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"running": ai_trading.is_running(user.id), "config": config}


@router.post("/stop", response_model=Dict[str, Any])
async def stop_ai_trading(user: CurrentUser) -> Dict[str, Any]:
    """Stop this account's AI trader (config.enabled = False, loop cancelled)."""
    config = ai_trading.stop(user.id)
    return {"running": ai_trading.is_running(user.id), "config": config}


@router.post("/cycle", response_model=Dict[str, Any])
async def run_one_cycle(user: CurrentUser) -> Dict[str, Any]:
    """Evaluate every configured symbol once for the caller and act on decisions."""
    try:
        return await ai_trading.run_cycle(user.id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AI cycle failed: {exc}") from exc


@router.get("/log", response_model=List[Dict[str, Any]])
async def get_ai_trading_log(
    user: CurrentUser, limit: int = Query(50, ge=1, le=500)
) -> List[Dict[str, Any]]:
    """Recent AI decisions for this account, with confidence and reasoning."""
    return ai_trading.recent_log(user.id, limit)


@router.get("/memory/{symbol}", response_model=Dict[str, Any])
async def get_symbol_memory(symbol: str, user: CurrentUser) -> Dict[str, Any]:
    """This account's learned experience for one symbol."""
    return {
        "symbol": symbol.upper(),
        "journal": ai_trading.journal_memory(user.id, symbol.upper()),
        "backtest_edge": ai_trading.backtest_edge(user.id),
    }
