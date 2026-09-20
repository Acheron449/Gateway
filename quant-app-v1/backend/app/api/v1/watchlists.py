from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from app.auth import get_current_user, CurrentUser

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

class WatchlistCreate(BaseModel):
    name: str
    symbols: List[str] = []

class WatchlistUpdate(BaseModel):
    name: Optional[str] = None
    symbols: Optional[List[str]] = None

class WatchlistOut(BaseModel):
    id: str
    name: str
    symbols: List[str]

# In-memory per user (dev); replace with DB in prod
_user_watchlists = {}

@router.get("", response_model=List[WatchlistOut])
def list_watchlists(user: CurrentUser):
    return _user_watchlists.get(user.id, [])

@router.post("", response_model=WatchlistOut)
def create_watchlist(payload: WatchlistCreate, user: CurrentUser):
    import uuid
    wl_id = str(uuid.uuid4())[:8]
    wl = {"id": wl_id, "name": payload.name, "symbols": payload.symbols}
    _user_watchlists.setdefault(user.id, []).append(wl)
    return wl

@router.get("/{wl_id}", response_model=WatchlistOut)
def get_watchlist(wl_id: str, user: CurrentUser):
    for wl in _user_watchlists.get(user.id, []):
        if wl["id"] == wl_id:
            return wl
    raise HTTPException(status_code=404, detail="Watchlist not found")

@router.patch("/{wl_id}", response_model=WatchlistOut)
def update_watchlist(wl_id: str, payload: WatchlistUpdate, user: CurrentUser):
    for wl in _user_watchlists.get(user.id, []):
        if wl["id"] == wl_id:
            if payload.name is not None:
                wl["name"] = payload.name
            if payload.symbols is not None:
                wl["symbols"] = payload.symbols
            return wl
    raise HTTPException(status_code=404, detail="Watchlist not found")

@router.delete("/{wl_id}")
def delete_watchlist(wl_id: str, user: CurrentUser):
    wls = _user_watchlists.get(user.id, [])
    for i, wl in enumerate(wls):
        if wl["id"] == wl_id:
            wls.pop(i)
            return {"deleted": True}
    raise HTTPException(status_code=404, detail="Watchlist not found")