from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.services import secrets_vault


router = APIRouter(prefix="/vault", tags=["vault"])


class SecretUpsert(BaseModel):
    value: str = Field(min_length=1, max_length=4096)
    note: str = ""


class SecretValueResponse(BaseModel):
    name: str
    value: str


@router.get("", response_model=List[Dict[str, Any]])
async def list_secrets(user: CurrentUser) -> List[Dict[str, Any]]:
    """List stored secret names/metadata (values are never returned)."""
    try:
        return secrets_vault.list_secrets()
    except secrets_vault.VaultError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/{name:path}", response_model=Dict[str, Any])
async def put_secret(name: str, payload: SecretUpsert, user: CurrentUser) -> Dict[str, Any]:
    """Create or replace a secret (encrypted with Fernet at rest)."""
    try:
        return secrets_vault.set_secret(name, payload.value, payload.note)
    except secrets_vault.VaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{name:path}/reveal", response_model=SecretValueResponse)
async def reveal_secret(name: str, user: CurrentUser) -> SecretValueResponse:
    """Decrypt one secret for the authenticated user."""
    try:
        value = secrets_vault.get_secret(name)
    except secrets_vault.VaultError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if value is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    return SecretValueResponse(name=name, value=value)


@router.delete("/{name:path}", status_code=204)
async def delete_secret(name: str, user: CurrentUser):
    try:
        deleted = secrets_vault.delete_secret(name)
    except secrets_vault.VaultError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Secret not found")
