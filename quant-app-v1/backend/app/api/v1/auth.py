import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from app.models.user import User, UserPreferences
from app.auth import create_access_token, get_current_user, CurrentUser
from app.services.database import (
    create_user, get_user_by_email, get_user_by_id,
    get_preferences, upsert_preferences,
)

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    name: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


@router.post("/register")
def register(payload: RegisterRequest):
    email = payload.email.strip().lower()
    if get_user_by_email(email):
        raise HTTPException(status_code=400, detail="User exists")
    user_id = os.urandom(8).hex()
    create_user(user_id=user_id, email=email, hashed_password=pwd_context.hash(payload.password), name=payload.name)
    # Issue the token immediately so clients land in a signed-in state after
    # signup (mirrors /login's response shape).
    token = create_access_token({"sub": user_id, "email": email})
    return {"id": user_id, "email": email, "name": payload.name, "access_token": token, "token_type": "bearer"}


@router.post("/login")
def login(payload: LoginRequest):
    email = payload.email.strip().lower()
    user = get_user_by_email(email)
    if not user or not pwd_context.verify(payload.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return {"access_token": token, "token_type": "bearer"}
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