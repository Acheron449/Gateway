"""Round-trip coverage for the persisted preferences endpoints.

``PATCH /auth/preferences`` and the ``/preferences`` router both write to
``app.services.database.upsert_preferences`` (SQLite locally, Supabase RPCs
in the cloud). The write path used to hand pydantic ``Watchlist`` /
``Layout`` models straight to ``json.dumps`` / httpx's JSON encoder, which
cannot serialize them — every non-empty watchlist 500'd. These tests pin the
round-trip through the HTTP layer in both directions.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.api.main import app
from app.services.database import get_connection

_EMAIL = f"prefs-{uuid.uuid4().hex[:8]}@local.test"
_PASSWORD = "Sup3rSecret!"
_WATCHLISTS = [{"id": "wl1", "name": "Main", "symbols": ["MSFT", "NVDA"]}]
_SAVED_LAYOUTS = {
    "MSFT": {
        "symbol": "MSFT",
        "tab": "chart",
        "timeframe": "1d",
        "indicators": ["ema"],
        "inspector_width": 320,
    }
}


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _signup(client: httpx.AsyncClient) -> dict[str, str]:
    res = await client.post("/auth/register", json={"email": _EMAIL, "password": _PASSWORD, "name": "Prefs"})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def cleanup_user():
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM preferences WHERE user_id IN (SELECT id FROM users WHERE email = ?)", (_EMAIL,))
        conn.execute("DELETE FROM users WHERE email = ?", (_EMAIL,))
        conn.commit()


@pytest.mark.asyncio
async def test_auth_preferences_round_trips_non_empty_watchlists(cleanup_user) -> None:
    async with await _client() as client:
        headers = await _signup(client)

        res = await client.patch(
            "/auth/preferences",
            headers=headers,
            json={
                "theme": "light",
                "default_timezone": "Europe/London",
                "watchlists": _WATCHLISTS,
                "saved_layouts": _SAVED_LAYOUTS,
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["theme"] == "light"
        assert body["watchlists"] == _WATCHLISTS

        # Stored prefs are visible through /auth/me (what the SPA reads).
        res = await client.get("/auth/me", headers=headers)
        assert res.status_code == 200, res.text
        prefs = res.json()["preferences"]
        assert prefs["theme"] == "light"
        assert prefs["default_timezone"] == "Europe/London"
        assert prefs["watchlists"] == _WATCHLISTS
        assert prefs["saved_layouts"]["MSFT"]["inspector_width"] == 320


@pytest.mark.asyncio
async def test_preferences_router_reads_and_writes_the_database(cleanup_user) -> None:
    async with await _client() as client:
        headers = await _signup(client)

        # Defaults before anything is written.
        res = await client.get("/preferences", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["theme"] == "dark"

        res = await client.patch(
            "/preferences",
            headers=headers,
            json={
                "theme": "light",
                "default_timezone": "UTC",
                "watchlists": _WATCHLISTS,
                "saved_layouts": {},
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["theme"] == "light"

        # The other route sees the same row — storage is shared, not in-memory.
        res = await client.get("/auth/me", headers=headers)
        assert res.json()["preferences"]["theme"] == "light"
        assert res.json()["preferences"]["watchlists"] == _WATCHLISTS


@pytest.mark.asyncio
async def test_preferences_endpoints_require_auth(cleanup_user) -> None:
    async with await _client() as client:
        res = await client.get("/preferences")
        assert res.status_code == 401
        res = await client.patch("/preferences", json={"theme": "light"})
        assert res.status_code == 401
