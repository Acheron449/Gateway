from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from app.auth import get_current_user, CurrentUser
from app.services.database import (
    create_watchlist, list_watchlists, update_watchlist, delete_watchlist,
)

router = APIRouter(prefix="/watchlists", tags=["watchlists"])

class WatchlistCreate(BaseModel):
    name: str
    symbols: List[str] = []

class WatchlistUpdate(BaseModel):
    name: Optional[str] = None
    symbols: Optional[List[str]] = None

@router.get("", response_model=List[dict])
def list_watchlists_route(user: CurrentUser):
    return list_watchlists(user.id)

@router.post("", response_model=dict)
def create_watchlist_route(payload: WatchlistCreate, user: CurrentUser):
    import uuid
    wl_id = str(uuid.uuid4())[:8]
    create_watchlist(wl_id=wl_id, user_id=user.id, name=payload.name, symbols=payload.symbols)
    return list_watchlists(user.id)[0] if list_watchlists(user.id) else {"id": wl_id}

@router.get("/{wl_id}", response_model=dict)
def get_watchlist(wl_id: str, user: CurrentUser):
    for wl in list_watchlists(user.id):
        if wl["id"] == wl_id:
            return wl
    raise HTTPException(status_code=404, detail="Watchlist not found")

@router.patch("/{wl_id}", response_model=dict)
def update_watchlist_route(wl_id: str, payload: WatchlistUpdate, user: CurrentUser):
    for wl in list_watchlists(user.id):
        if wl["id"] == wl_id:
            update_watchlist(wl_id, name=payload.name, symbols=payload.symbols)
            for w in list_watchlists(user.id):
                if w["id"] == wl_id:
                    return w
    raise HTTPException(status_code=404, detail="Watchlist not found")

@router.delete("/{wl_id}")
def delete_watchlist_route(wl_id: str, user: CurrentUser):
    for wl in list_watchlists(user.id):
        if wl["id"] == wl_id:
            delete_watchlist(wl_id)
            return {"deleted": True}
    raise HTTPException(status_code=404, detail="Watchlist not found")