"""Exposure-stopgap tests for private APIs backed by shared state."""
from __future__ import annotations

import os

import httpx
import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from app.api.main import app
from app.auth import create_access_token


_PRIVATE_ROUTES = [
    ("GET", "/portfolio"),
    ("GET", "/strategies"),
    ("GET", "/journal"),
    ("GET", "/risk/config"),
    ("GET", "/ai-trading"),
    ("GET", "/settings/providers"),
    ("GET", "/vault"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _PRIVATE_ROUTES)
async def test_private_routes_require_authentication_before_work(method: str, path: str):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path)
    assert response.status_code == 401, (method, path, response.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), _PRIVATE_ROUTES)
async def test_shared_private_routes_are_unavailable_until_owner_isolation(method: str, path: str):
    token = create_access_token({"sub": "exposure-stopgap-user", "email": "user@example.test"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503, (method, path, response.text)
    assert response.json() == {"detail": "Private data unavailable until account isolation is enabled"}


@pytest.mark.asyncio
async def test_journal_live_sync_requires_auth_then_fails_closed():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        anonymous = await client.post("/journal/sync-live")
        token = create_access_token({"sub": "exposure-stopgap-user", "email": "user@example.test"})
        authenticated = await client.post(
            "/journal/sync-live", headers={"Authorization": f"Bearer {token}"}
        )
    assert anonymous.status_code == 401
    assert authenticated.status_code == 503
    assert authenticated.json() == {"detail": "Private data unavailable until account isolation is enabled"}
