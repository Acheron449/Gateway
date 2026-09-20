"""Authentication API routes."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import (
    create_access_token,
    get_current_user,
    CurrentUser,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Stricter rate limiter for auth endpoints
auth_limiter = Limiter(key_func=get_remote_address, default_limits=["5/minute", "20/hour"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None = None


# In-memory user store (replace with database in production)
# In production, use proper user database with hashed passwords
_users_db: dict[str, dict] = {}


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    import bcrypt
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash."""
    import bcrypt
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@auth_limiter.limit("5/minute")
async def register(request: Request, register_request: RegisterRequest) -> TokenResponse:
    """Register a new user."""
    if register_request.email in _users_db:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered"
        )
    
    user_id = register_request.email  # Use email as user_id for simplicity
    hashed_password = hash_password(register_request.password)
    
    _users_db[register_request.email] = {
        "id": user_id,
        "email": register_request.email,
        "name": register_request.name,
        "password_hash": hashed_password,
    }
    
    access_token = create_access_token(
        data={"sub": user_id, "email": register_request.email},
        expires_delta=timedelta(minutes=60 * 24)
    )
    
    return TokenResponse(
        access_token=access_token,
        user={"id": user_id, "email": register_request.email, "name": register_request.name}
    )


@router.post("/login", response_model=TokenResponse)
@auth_limiter.limit("5/minute")
async def login(request: Request, login_request: LoginRequest) -> TokenResponse:
    """Login and get access token."""
    user = _users_db.get(login_request.email)
    if not user or not verify_password(login_request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
    
    access_token = create_access_token(
        data={"sub": user["id"], "email": user["email"]},
        expires_delta=timedelta(minutes=60 * 24)
    )
    
    return TokenResponse(
        access_token=access_token,
        user={"id": user["id"], "email": user["email"], "name": user.get("name")}
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> UserResponse:
    """Get current user info."""
    user = _users_db.get(current_user.email)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(id=user["id"], email=user["email"], name=user.get("name"))


@router.post("/logout")
async def logout() -> dict:
    """Logout (client-side token removal)."""
    return {"message": "Logged out successfully"}