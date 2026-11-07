"""NFR-29: the site records notice acceptance per user, idempotently."""

from __future__ import annotations

import uuid

import httpx
import pytest

import app.services.database as database
from app.api.main import app
from app.services.database import get_connection

_PASSWORD = "Sup3rSecret!"
_EMAIL_ONE = f"notice-{uuid.uuid4().hex[:8]}@local.test"
_EMAIL_TWO = f"notice-{uuid.uuid4().hex[:8]}@local.test"


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _signup(client: httpx.AsyncClient, email: str) -> dict[str, str]:
    res = await client.post("/auth/register", json={"email": email, "password": _PASSWORD, "name": "Notice"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def cleanup_notice_users():
    yield
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM notice_acceptances WHERE user_id IN (SELECT id FROM users WHERE email IN (?, ?))",
            (_EMAIL_ONE, _EMAIL_TWO),
        )
        conn.execute("DELETE FROM users WHERE email IN (?, ?)", (_EMAIL_ONE, _EMAIL_TWO))
        conn.commit()


@pytest.mark.asyncio
async def test_notice_acceptance_is_per_user_and_idempotent(cleanup_notice_users) -> None:
    async with await _client() as client:
        first = await _signup(client, _EMAIL_ONE)
        second = await _signup(client, _EMAIL_TWO)

        status = await client.get("/notices", headers=first)
        assert status.status_code == 200, status.text
        assert status.json()["accepted"] is False
        assert status.json()["accepted_at"] is None

        accepted = await client.post("/notices", headers=first)
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert body["accepted"] is True
        assert body["version"] == "2026-11-07"
        assert body["accepted_at"]

        again = await client.post("/notices", headers=first)
        assert again.status_code == 200
        assert again.json()["accepted"] is True

        reread = await client.get("/notices", headers=first)
        assert reread.json()["accepted"] is True
        assert reread.json()["version"] == body["version"]

        # A second account has its own record and is still prompted.
        other = await client.get("/notices", headers=second)
        assert other.status_code == 200
        assert other.json()["accepted"] is False


@pytest.mark.asyncio
async def test_notice_acceptance_requires_authentication(cleanup_notice_users) -> None:
    async with await _client() as client:
        assert (await client.get("/notices")).status_code == 401
        assert (await client.post("/notices")).status_code == 401


def test_notice_acceptance_uses_supabase_rpcs(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []
    accepted = {"version": "2026-11-07", "accepted_at": "2026-11-07T12:00:00+00:00"}

    def fake_rpc(fn: str, payload: dict):
        calls.append((fn, payload))
        return dict(accepted)

    monkeypatch.setattr(database, "_supabase_enabled", lambda: True)
    monkeypatch.setattr(database, "_sb_rpc", fake_rpc)

    assert database.get_notice_acceptance("user-1") == accepted
    assert database.record_notice_acceptance("user-1", "2026-11-07") == accepted
    assert calls == [
        ("gw_get_notice_acceptance", {"p_user_id": "user-1"}),
        (
            "gw_accept_notice",
            {"p_user_id": "user-1", "p_version": "2026-11-07"},
        ),
    ]


def test_notice_acceptance_absent_in_supabase_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(database, "_supabase_enabled", lambda: True)
    monkeypatch.setattr(database, "_sb_rpc", lambda fn, payload: None)

    assert database.get_notice_acceptance("user-2") is None
    with pytest.raises(RuntimeError, match="returned no acceptance"):
        database.record_notice_acceptance("user-2", "2026-11-07")
