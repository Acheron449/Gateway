from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, List, Optional
from app.auth import get_current_user, CurrentUser
from app.models.user import Layout

router = APIRouter(prefix="/layouts", tags=["layouts"])

class LayoutCreate(BaseModel):
    symbol: str
    tab: str
    timeframe: str
    indicators: List[str] = []
    inspector_width: int = 320

class LayoutUpdate(BaseModel):
    symbol: Optional[str] = None
    tab: Optional[str] = None
    timeframe: Optional[str] = None
    indicators: Optional[List[str]] = None
    inspector_width: Optional[int] = None

# In-memory per user (dev)
_user_layouts = {}

@router.get("", response_model=Dict[str, Layout])
def list_layouts(user: CurrentUser):
    return _user_layouts.get(user.id, {})

@router.post("", response_model=Layout)
def create_layout(payload: LayoutCreate, user: CurrentUser):
    _user_layouts.setdefault(user.id, {})[payload.symbol] = payload.model_dump()
    return _user_layouts[user.id][payload.symbol]

@router.get("/{symbol}", response_model=Layout)
def get_layout(symbol: str, user: CurrentUser):
    lay = _user_layouts.get(user.id, {}).get(symbol)
    if not lay:
        raise HTTPException(status_code=404, detail="Layout not found")
    return lay

@router.patch("/{symbol}", response_model= Layout)
def update_layout(symbol: str, payload: LayoutUpdate, user: CurrentUser):
    lay = _user_layouts.get(user.id, {}).get(symbol)
    if not lay:
        raise HTTPException(status_code=404, detail="Layout not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        lay[k] = v
    return lay

@router.delete("/{symbol}")
def delete_layout(symbol: str, user: CurrentUser):
    if symbol in _user_layouts.get(user.id, {}):
        del _user_layouts[user.id][symbol]
        return {"deleted": True}
    raise HTTPException(status_code=404, detail="Layout not found")
