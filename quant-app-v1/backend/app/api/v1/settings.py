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
    """Test a stored provider key without returning raw provider errors.

    Probes each capability independently so a partial entitlement (e.g.
    Finnhub's premium-only economic calendar returning 403 on free keys)
    is reported as such instead of failing the whole test, while a rejected
    key (401/402) fails the test with an explicit message.
    """
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

    from app.providers.base import ProviderUnavailableError

    def _status_of(exc: Exception) -> int | None:
        return getattr(exc, "status_code", None)

    async def _probe(name: str, call):
        try:
            result = await call()
            return {"capability": name, "ok": True, "count": len(result), "status": None, "detail": ""}
        except ProviderUnavailableError as exc:
            return {"capability": name, "ok": False, "count": 0, "status": _status_of(exc), "detail": str(exc)}
        except Exception as exc:
            return {"capability": name, "ok": False, "count": 0, "status": None, "detail": str(exc) or "failed"}

    # Probe only capabilities the provider actually implements.
    probes: list[tuple[str, Any]] = []
    if callable(getattr(provider_instance, "quote", None)):
        probes.append(("quote", lambda: provider_instance.quote("AAPL")))
    if callable(getattr(provider_instance, "news", None)):
        probes.append(("news", lambda: provider_instance.news(symbol="AAPL", limit=1)))
    if callable(getattr(provider_instance, "calendar", None)):
        probes.append(("calendar", lambda: provider_instance.calendar(limit=1)))

    results: list[Dict[str, Any]] = []
    try:
        for name, call in probes:
            results.append(await _probe(name, call))
    finally:
        await provider_instance.close()

    if not results:
        return {
            "success": False,
            "message": "Provider exposes no testable capabilities",
            "configured": True,
            "status": "unavailable",
            "news_count": 0,
            "calendar_count": 0,
            "capabilities": {},
        }
    by_name = {r["capability"]: r for r in results}
    capabilities = {r["capability"]: ("ok" if r["ok"] else "failed") for r in results}

    def _detail(name: str) -> tuple[bool, int | None, str]:
        r = by_name[name]
        return r["ok"], r["status"], r["detail"]

    quote_ok, quote_status, quote_detail = _detail("quote")
    news_ok, news_status, news_detail = _detail("news")
    calendar_ok, calendar_status, calendar_detail = _detail("calendar")

    # A 403 on a capability usually means the plan does not include it
    # (Finnhub economic calendar is premium-only), not that the key is bad.
    premium_only = {name for name, r in by_name.items() if not r["ok"] and r["status"] == 403}
    for name in premium_only:
        capabilities[name] = "premium"

    auth_rejected = any(
        r["status"] in (401, 402)
        for r in by_name.values()
        if r["status"] is not None
    )

    working = [name for name in ("quote", "news", "calendar") if by_name[name]["ok"]]
    failed = [name for name in ("quote", "news", "calendar") if not by_name[name]["ok"]]

    if auth_rejected or not working:
        # Key-level failure: rejected outright, or nothing usable responded.
        if auth_rejected:
            message = "Finnhub rejected the key (HTTP 401/402). Double-check the saved API key."
        else:
            first_failed = by_name[failed[0]]
            message = f"Provider test failed: {first_failed['detail']}"
        return {
            "success": False,
            "message": message,
            "configured": True,
            "status": "unavailable",
            "news_count": by_name["news"]["count"],
            "calendar_count": by_name["calendar"]["count"],
            "capabilities": capabilities,
        }

    premium_names = {"quote": "quotes", "news": "news", "calendar": "the economic calendar"}
    parts = [f"{premium_names[name]} verified" for name in working]
    message = f"Key works: {', '.join(parts)}"
    if premium_only:
        message += f"; {', '.join(premium_names[name] for name in sorted(premium_only))} require(s) a premium plan (HTTP 403)"

    return {
        "success": True,
        "message": message,
        "configured": True,
        "status": "healthy" if not failed else "degraded",
        "news_count": by_name["news"]["count"],
        "calendar_count": by_name["calendar"]["count"],
        "capabilities": capabilities,
    }
