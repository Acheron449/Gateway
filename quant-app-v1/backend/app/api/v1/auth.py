import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from app.models.user import User, UserPreferences
from app.auth import create_access_token, get_current_user, CurrentUser, local_auth_enabled
from app.services.database import (
    create_user, get_user_by_email, get_user_by_id,
    get_preferences, upsert_preferences,
    update_user_profile, record_deletion_request,
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


def _require_local_auth():
    """Password login only exists when JWT_SECRET_KEY is configured.

    Auth0-only deployments (AUTH0_DOMAIN set, no local secret) still serve
    /auth/me, /auth/preferences and token verification — they just can't
    issue local tokens.
    """
    if not local_auth_enabled():
        raise HTTPException(
            status_code=503,
            detail="Password login is disabled on this deployment — sign in with Auth0",
        )


@router.post("/register")
def register(payload: RegisterRequest):
    _require_local_auth()
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
    _require_local_auth()
    email = payload.email.strip().lower()
    user = get_user_by_email(email)
    if not user or not pwd_context.verify(payload.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user["id"], "email": user["email"]})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(user: CurrentUser):
    """Current profile + preferences.

    Name/email are read from the stored user row (the token's claims are a
    snapshot from sign-in), so edits made through ``PATCH /auth/me`` show up
    immediately without forcing a fresh token.
    """
    prefs = get_preferences(user.id)
    record = get_user_by_id(user.id) or {}
    return {
        "id": user.id,
        "email": record.get("email") or user.email,
        "name": record.get("name") if record.get("name") is not None else user.name,
        "preferences": prefs,
    }


class ProfileUpdate(BaseModel):
    """Partial update of the signed-in user's personal details."""
    name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(default=None, min_length=3, max_length=255)


@router.patch("/me")
def update_me(payload: ProfileUpdate, user: CurrentUser):
    """Edit personal details (display name and/or email)."""
    name = payload.name.strip() if payload.name is not None else None
    email = payload.email.strip().lower() if payload.email is not None else None
    if name == "":
        name = None
    if email == "":
        email = None
    if name is None and email is None:
        raise HTTPException(status_code=400, detail="Nothing to update")

    try:
        updated = update_user_profile(user.id, name=name, email=email)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "id": updated.get("id", user.id),
        "email": updated.get("email", user.email),
        "name": updated.get("name"),
    }


class DeletionRequest(BaseModel):
    """Request account deletion — recorded as a ticket, not executed."""
    reason: Optional[str] = Field(default=None, max_length=500)
    confirm: bool = False


@router.post("/delete-request")
def request_deletion(payload: DeletionRequest, user: CurrentUser):
    """Queue an account-deletion request for review.

    Destructive deletion is never performed inline; the user receives a ticket
    they can quote to an operator.
    """
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="Confirm the deletion request before submitting",
        )
    reason = payload.reason.strip() if payload.reason else None
    ticket = record_deletion_request(user.id, user.email, reason)
    return {
        "ticket": ticket,
        "status": "pending",
        "message": (
            "Deletion requested. Your account stays active until the request "
            "is reviewed — keep this ticket to follow up."
        ),
    }


@router.post("/logout")
def logout():
    return {"message": "Logged out; client should discard token"}


@router.post("/refresh")
def refresh(user: CurrentUser):
    _require_local_auth()
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