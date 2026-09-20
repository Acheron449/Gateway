import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from passlib.context import CryptContext
from app.models.user import User, UserPreferences
from app.auth import create_access_token, get_current_user, CurrentUser
from app.services.database import (
    create_user, get_user_by_email, get_user_by_id,
    get_preferences, upsert_preferences,
)

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("/register")
def register(email: str, password: str, name: Optional[str] = None):
    if get_user_by_email(email):
        raise HTTPException(status_code=400, detail="User exists")
    user_id = os.urandom(8).hex()
    create_user(user_id=user_id, email=email, hashed_password=pwd_context.hash(password), name=name)
    return {"id": user_id, "email": email, "name": name}


@router.post("/login")
def login(email: str, password: str):
    user = get_user_by_email(email)
    if not user or not pwd_context.verify(password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(user: CurrentUser):
    prefs = get_preferences(user.id)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "preferences": prefs,
    }


@router.post("/logout")
def logout():
    return {"message": "Logged out; client should discard token"}


@router.post("/refresh")
def refresh(user: CurrentUser):
    token = create_access_token({"sub": user.id, "email": user.email})
    return {"access_token": token}


@router.patch("/preferences")
def update_preferences(prefs: UserPreferences, user: CurrentUser):
    upsert_preferences(
        user.id,
        theme=prefs.theme,
        default_timezone=prefs.default_timezone,
        watchlists=prefs.watchlists,
        saved_layouts=prefs.saved_layouts,
    )
    return get_preferences(user.id)