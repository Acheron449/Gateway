"""Coverage for account personal-details editing and deletion requests.

``PATCH /auth/me`` edits the signed-in user's name/email and
``POST /auth/delete-request`` queues a reviewable ticket instead of destroying
the account inline — both added with the account settings UI (item 19). These
tests pin the HTTP contract: the partial-update semantics, the duplicate-email
conflict, the required confirmation, and that a request is recorded rather than
executed.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.api.main import app
from app.services.database import get_connection

_EMAIL = f"acct-{uuid.uuid4().hex[:8]}@local.test"
_NEW_EMAIL = f"acct-renamed-{uuid.uuid4().hex[:8]}@local.test"
_PASSWORD = "Sup3rSecret!"


async def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _signup(client: httpx.AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/auth/register", json={"email": _EMAIL, "password": _PASSWORD, "name": "Original"}
    )
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def cleanup_user():
    yield
    with get_connection() as conn:
        for address in (_EMAIL, _NEW_EMAIL):
            conn.execute(
                "DELETE FROM deletion_requests WHERE user_id IN (SELECT id FROM users WHERE email = ?)",
                (address,),
            )
            conn.execute(
                "DELETE FROM preferences WHERE user_id IN (SELECT id FROM users WHERE email = ?)",
                (address,),
            )
            conn.execute("DELETE FROM users WHERE email = ?", (address,))
        conn.commit()


@pytest.mark.asyncio
async def test_patch_me_updates_name_and_email(cleanup_user) -> None:
    async with await _client() as client:
        headers = await _signup(client)

        res = await client.patch(
            "/auth/me", headers=headers, json={"name": "Renamed", "email": _NEW_EMAIL}
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["name"] == "Renamed"
        assert body["email"] == _NEW_EMAIL

        # The change is visible through GET /auth/me (what the SPA re-reads).
        res = await client.get("/auth/me", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["name"] == "Renamed"
        assert res.json()["email"] == _NEW_EMAIL


@pytest.mark.asyncio
async def test_patch_me_is_partial_and_requires_auth(cleanup_user) -> None:
    async with await _client() as client:
        headers = await _signup(client)

        # Only the name is supplied — email must be left untouched.
        res = await client.patch("/auth/me", headers=headers, json={"name": "OnlyName"})
        assert res.status_code == 200, res.text
        assert res.json()["email"] == _EMAIL

        # Nothing to update is a 400, not a silent no-op.
        res = await client.patch("/auth/me", headers=headers, json={})
        assert res.status_code == 400

        # Signed-out callers are rejected.
        res = await client.patch("/auth/me", json={"name": "Nope"})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_patch_me_rejects_duplicate_email(cleanup_user) -> None:
    async with await _client() as client:
        first = await _signup(client)

        other_email = f"taken-{uuid.uuid4().hex[:8]}@local.test"
        res = await client.post(
            "/auth/register", json={"email": other_email, "password": _PASSWORD}
        )
        assert res.status_code == 200, res.text

        res = await client.patch("/auth/me", headers=first, json={"email": other_email})
        assert res.status_code == 409, res.text

        with get_connection() as conn:
            conn.execute("DELETE FROM users WHERE email = ?", (other_email,))
            conn.commit()


@pytest.mark.asyncio
async def test_delete_request_requires_confirmation_and_is_recorded(cleanup_user) -> None:
    async with await _client() as client:
        headers = await _signup(client)

        # Unconfirmed requests are refused.
        res = await client.post("/auth/delete-request", headers=headers, json={"confirm": False})
        assert res.status_code == 400, res.text

        res = await client.post(
            "/auth/delete-request",
            headers=headers,
            json={"confirm": True, "reason": "no longer needed"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ticket"].startswith("DEL-")
        assert body["status"] == "pending"

        # A ticket is queued — the account itself is NOT deleted.
        with get_connection() as conn:
            row = conn.execute(
                "SELECT user_id, reason, status FROM deletion_requests WHERE ticket = ?",
                (body["ticket"],),
            ).fetchone()
        assert row is not None
        assert row[1] == "no longer needed"
        assert row[2] == "pending"

        res = await client.get("/auth/me", headers=headers)
        assert res.status_code == 200, res.text
