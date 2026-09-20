from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from app.auth import get_current_user, CurrentUser
from app.models.user import UserPreferences

router = APIRouter(prefix="/preferences", tags=["preferences"])

# In-memory per user (dev)
_user_prefs = {}

@router.get("", response_model=UserPreferences)
def get_preferences(user: CurrentUser):
    return _user_prefs.get(user.id, UserPreferences())

@router.patch("", response_model=UserPreferences)
def update_preferences(prefs: UserPreferences, user: CurrentUser):
    _user_prefs[user.id] = prefs
    return prefs