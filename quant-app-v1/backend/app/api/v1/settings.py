from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.providers.registry import (
    _delete_api_key,
    _store_api_key,
    get_provider,
    has_stored_key,
    list_providers as registry_list_providers,
)


router = APIRouter(prefix="/settings/providers", tags=["settings"])


class ProviderMetaResponse(BaseModel):
    name: str
    version: str
    endpoint: str
    requires_api_key: bool
    rate_limit_per_min: Optional[int]


class ProviderStatusResponse(BaseModel):
    name: str
    meta: ProviderMetaResponse
    configured: bool
    has_stored_key: bool


class ProviderKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, description="API key to store")


class ProviderKeyResponse(BaseModel):
    provider: str
    stored: bool
    message: str


class ProviderKeyDeleteResponse(BaseModel):
    provider: str
    deleted: bool
    message: str


@router.get("", response_model=List[ProviderStatusResponse])
async def list_providers() -> List[ProviderStatusResponse]:
    """List providers without exposing credentials."""
    results = []
    for name, meta in registry_list_providers().items():
        provider_instance = get_provider(name)
        results.append(
            ProviderStatusResponse(
                name=name,
                meta=ProviderMetaResponse(**meta),
                configured=bool(provider_instance and provider_instance.is_configured),
                has_stored_key=has_stored_key(name),
            )
        )
    return results


@router.get("/{provider_name}", response_model=ProviderStatusResponse)
async def get_provider_status(provider_name: str) -> ProviderStatusResponse:
    """Get detailed status for a specific provider."""
    meta = next((value for name, value in registry_list_providers().items() if name.casefold() == provider_name.casefold()), None)
    if meta is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    provider_instance = get_provider(provider_name)
    return ProviderStatusResponse(
        name=meta["name"],
        meta=ProviderMetaResponse(**meta),
        configured=bool(provider_instance and provider_instance.is_configured),
        has_stored_key=has_stored_key(provider_name),
    )


@router.post("/{provider_name}/key", response_model=ProviderKeyResponse)
async def store_provider_key(
    provider_name: str,
    request: ProviderKeyRequest,
    user: CurrentUser,
) -> ProviderKeyResponse:
    """Store an encrypted API key for a supported BYOK provider."""
    meta = next((value for name, value in registry_list_providers().items() if name.casefold() == provider_name.casefold()), None)
    if meta is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if meta["name"] != "Finnhub":
        raise HTTPException(status_code=400, detail="This provider does not support browser-managed API keys")

    try:
        _store_api_key(meta["name"], request.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return ProviderKeyResponse(
        provider=meta["name"],
        stored=True,
        message="API key stored successfully",
    )


@router.delete("/{provider_name}/key", response_model=ProviderKeyDeleteResponse)
async def delete_provider_key(
    provider_name: str,
    user: CurrentUser,
) -> ProviderKeyDeleteResponse:
    """Delete a stored API key."""
    meta = next((value for name, value in registry_list_providers().items() if name.casefold() == provider_name.casefold()), None)
    if meta is None:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not has_stored_key(meta["name"]):
        raise HTTPException(status_code=404, detail="No stored key found for this provider")

    _delete_api_key(meta["name"])
    return ProviderKeyDeleteResponse(
        provider=meta["name"],
        deleted=True,
        message="API key deleted successfully",
    )


@router.get("/{provider_name}/test", response_model=Dict[str, Any])
async def test_provider_key(
    provider_name: str,
    user: CurrentUser,
) -> Dict[str, Any]:
    """Test a stored provider key without returning raw provider errors."""
    meta = next((value for name, value in registry_list_providers().items() if name.casefold() == provider_name.casefold()), None)
    if meta is None:
        raise HTTPException(status_code=404, detail="Provider not found")

    provider_instance = get_provider(meta["name"])
    if provider_instance is None or not provider_instance.is_configured:
        return {
            "success": False,
            "message": "No usable provider key is configured",
            "configured": False,
        }

    try:
        news = await provider_instance.news(symbol="AAPL", limit=1)
        calendar = await provider_instance.calendar(limit=1)
        return {
            "success": True,
            "message": "Provider test completed",
            "configured": True,
            "status": "healthy",
            "news_count": len(news),
            "calendar_count": len(calendar),
        }
    except Exception:
        return {
            "success": False,
            "message": "Provider test failed",
            "configured": provider_instance.is_configured,
            "status": "unavailable",
            "news_count": 0,
            "calendar_count": 0,
        }
    finally:
        await provider_instance.close()
