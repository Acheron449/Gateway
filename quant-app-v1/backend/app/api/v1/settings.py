from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.provider_registry import (
    _PROVIDERS,
    _load_settings,
    _save_settings,
    _read_api_key,
    _store_api_key,
    _make_fernet_key,
    _encrypt_key,
    _decrypt_key,
)

router = APIRouter(prefix="/settings/providers", tags=["settings"])


# --- Models ---

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


class GenerateKeyResponse(BaseModel):
    fernet_key: str
    message: str


# --- Routes ---

@router.get("", response_model=List[ProviderStatusResponse])
async def list_providers() -> List[ProviderStatusResponse]:
    """List all available providers with their configuration status."""
    results = []
    for name, provider_class in _PROVIDERS.items():
        # Create a temporary instance to get meta
        temp_provider = provider_class(api_key="")
        meta = temp_provider.meta
        has_stored_key = bool(_read_api_key(name))
        results.append(ProviderStatusResponse(
            name=name,
            meta=ProviderMetaResponse(**meta),
            configured=temp_provider.is_configured,
            has_stored_key=has_stored_key,
        ))
    return results


@router.get("/{provider_name}", response_model=ProviderStatusResponse)
async def get_provider_status(provider_name: str) -> ProviderStatusResponse:
    """Get detailed status for a specific provider."""
    provider_class = _PROVIDERS.get(provider_name)
    if not provider_class:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    temp_provider = provider_class(api_key="")
    meta = temp_provider.meta
    has_stored_key = bool(_read_api_key(provider_name))
    
    return ProviderStatusResponse(
        name=provider_name,
        meta=ProviderMetaResponse(**meta),
        configured=temp_provider.is_configured,
        has_stored_key=has_stored_key,
    )


@router.post("/{provider_name}/key", response_model=ProviderKeyResponse)
async def store_provider_key(provider_name: str, request: ProviderKeyRequest) -> ProviderKeyResponse:
    """Store an API key for a provider (BYOK)."""
    provider_class = _PROVIDERS.get(provider_name)
    if not provider_class:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    # Validate key by attempting to create provider instance
    try:
        provider_class(api_key=request.api_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid API key: {e}")
    
    # Store encrypted key
    _store_api_key(provider_name, request.api_key)
    
    return ProviderKeyResponse(
        provider=provider_name,
        stored=True,
        message="API key stored successfully",
    )


@router.delete("/{provider_name}/key", response_model=ProviderKeyDeleteResponse)
async def delete_provider_key(provider_name: str) -> ProviderKeyDeleteResponse:
    """Delete stored API key for a provider."""
    provider_class = _PROVIDERS.get(provider_name)
    if not provider_class:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    settings = _load_settings()
    if provider_name not in settings:
        raise HTTPException(status_code=404, detail="No stored key found for this provider")
    
    del settings[provider_name]
    _save_settings(settings)
    
    return ProviderKeyDeleteResponse(
        provider=provider_name,
        deleted=True,
        message="API key deleted successfully",
    )


@router.post("/generate-fernet-key", response_model=GenerateKeyResponse)
async def generate_fernet_key() -> GenerateKeyResponse:
    """Generate a new Fernet key for encrypting API keys at rest.
    
    This key should be stored in the GATEWAY_PROVIDER_KEY environment variable.
    Rotate rarely - changing it will make all stored keys undecryptable.
    """
    key = _make_fernet_key()
    return GenerateKeyResponse(
        fernet_key=key.decode(),
        message="Generated new Fernet key. Store it in GATEWAY_PROVIDER_KEY env var. Rotate rarely.",
    )


@router.get("/{provider_name}/test", response_model=Dict[str, Any])
async def test_provider_key(provider_name: str) -> Dict[str, Any]:
    """Test if a stored provider key works by making a test request."""
    provider_class = _PROVIDERS.get(provider_name)
    if not provider_class:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    api_key = _read_api_key(provider_name)
    if not api_key:
        return {
            "success": False,
            "message": "No stored API key found",
            "configured": False,
        }
    
    try:
        provider = provider_class(api_key=api_key)
        if not provider.is_configured:
            return {
                "success": False,
                "message": "Provider not properly configured",
                "configured": False,
            }
        
        # Test with a simple news call
        news = await provider.news(limit=1)
        calendar = await provider.calendar(limit=1)
        
        return {
            "success": True,
            "message": "API key works",
            "configured": True,
            "news_count": len(news),
            "calendar_count": len(calendar),
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Test failed: {str(e)}",
            "configured": False,
        }