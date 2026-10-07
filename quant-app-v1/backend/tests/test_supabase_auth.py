"""Supabase Auth token support in the shared ``decode_token`` chain.

Tokens issued by Supabase Auth are verified by introspecting them at GoTrue
(``GET /auth/v1/user``), never by decoding them with a shared secret — GoTrue
answers 200 only for tokens it accepts. These tests pin the dispatch, the
result/negative caching (an endpoint must not pay one outbound call per
request, and junk bearer tokens must not become an outbound-call stream),
and the lazy provisioning of the ``gateway_users`` profile row that
preferences depend on.
"""

from __future__ import annotations

import time

import httpx
import pytest
from jose import jwt as jose_jwt

import app.auth as auth
from app.services.database import get_user_by_id, get_connection

_SUPABASE_ISSUER = "https://npplleqigmjwnlkguynu.supabase.co/auth/v1"


def _supabase_token(sub: str, email: str, name: str | None = None) -> str:
    """A structurally real Supabase-shaped JWT (signature is never checked:
    verification happens at GoTrue, which these tests mock)."""
    claims = {
        "iss": _SUPABASE_ISSUER,
        "sub": sub,
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    if name:
        claims["name"] = name
    return jose_jwt.encode(claims, "not-the-real-secret", algorithm="HS256")


@pytest.fixture()
def supabase_env(monkeypatch):
    # SUPABASE_URL/KEY enable the auth introspection path; SUPABASE_RPC_SECRET
    # stays unset on purpose so database reads/writes remain on SQLite and the
    # suite never touches the real project.
    monkeypatch.setenv("SUPABASE_URL", "https://example-project.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "sb_publishable_test")
    auth._sb_cache.clear()
    yield
    auth._sb_cache.clear()


@pytest.fixture()
def introspect(monkeypatch):
    """Replace the outbound GoTrue call with a counting fake."""
    calls = {"n": 0}
    payload: dict = {"id": None, "email": None, "user_metadata": {}}

    def fake(token: str) -> dict | None:
        calls["n"] += 1
        return dict(payload) if payload.get("id") else None

    monkeypatch.setattr(auth, "_introspect_supabase", fake)
    return calls, payload


def test_supabase_token_decodes_to_tokendata(supabase_env, introspect) -> None:
    calls, payload = introspect
    payload.update({
        "id": "7f5c2b1e-1111-4222-8333-444455556666",
        "email": "ada@example.com",
        "user_metadata": {"name": "Ada"},
    })
    token = _supabase_token("7f5c2b1e-1111-4222-8333-444455556666", "ada@example.com")

    data = auth.decode_token(token)

    assert data is not None
    assert data.user_id == "7f5c2b1e-1111-4222-8333-444455556666"
    assert data.email == "ada@example.com"
    assert data.name == "Ada"
    assert data.exp.timestamp() > time.time()
    assert calls["n"] == 1


def test_introspection_result_is_cached(supabase_env, introspect) -> None:
    calls, payload = introspect
    payload.update({"id": "u-1", "email": "u@example.com", "user_metadata": {}})
    token = _supabase_token("u-1", "u@example.com")

    first = auth.decode_token(token)
    second = auth.decode_token(token)

    assert first is not None and second is not None
    assert first.user_id == second.user_id
    assert calls["n"] == 1, "second decode must be served from cache"


def test_rejected_token_fails_closed_and_is_negatively_cached(supabase_env, introspect) -> None:
    calls, _payload = introspect  # fake returns None — GoTrue said 401
    token = _supabase_token("u-404", "ghost@example.com")

    assert auth.decode_token(token) is None
    assert auth.decode_token(token) is None
    assert calls["n"] == 1, "rejected tokens must not trigger repeat outbound calls"


def test_junk_issuer_never_reaches_supabase_introspection(supabase_env, introspect) -> None:
    calls, _payload = introspect
    # A token that merely *claims* a non-Supabase issuer must not pay an
    # outbound call, and local tokens with no iss must take the local path.
    junk = jose_jwt.encode({"iss": "https://evil.example", "sub": "x", "exp": int(time.time()) + 60},
                           "nope", algorithm="HS256")
    assert auth.decode_token(junk) is None
    assert calls["n"] == 0

    local = auth.create_access_token({"sub": "local-user-1", "email": "local@example.com"})
    data = auth.decode_token(local)
    assert data is not None and data.user_id == "local-user-1"
    assert calls["n"] == 0, "local HS256 tokens must not trigger outbound calls"


def test_local_register_login_tokens_still_work_with_supabase_configured(supabase_env, introspect) -> None:
    calls, _payload = introspect
    token = auth.create_access_token({"sub": "abc123", "email": "keep@example.com"})
    data = auth.decode_token(token)
    assert data is not None and data.email == "keep@example.com"
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_auth_me_provisions_profile_row_for_supabase_user(supabase_env, introspect, tmp_path) -> None:
    calls, payload = introspect
    sub = "sb-provision-1"
    payload.update({"id": sub, "email": "provisioned@example.com",
                    "user_metadata": {"name": "Provisioned"}})
    token = _supabase_token(sub, "provisioned@example.com")

    from app.api.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        res = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == sub
    assert body["email"] == "provisioned@example.com"
    assert body["name"] == "Provisioned"
    assert body["preferences"]["theme"] == "dark"

    row = get_user_by_id(sub)
    assert row is not None, "profile row must exist for the preferences FK"
    assert row["email"] == "provisioned@example.com"
    assert row["hashed_password"] is None, "Supabase users have no local password"
    assert calls["n"] == 1

    with get_connection() as conn:
        conn.execute("DELETE FROM preferences WHERE user_id = ?", (sub,))
        conn.execute("DELETE FROM users WHERE id = ?", (sub,))
        conn.commit()
