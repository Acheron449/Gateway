"""Supabase-only identity tests (SRS FR-A1…A7).

Covers what replaced Auth0:

* local password tokens are confined to the ``local``/``test`` profiles;
* Supabase access tokens are verified by introspection and yield the GoTrue
  subject as the owner id;
* no Auth0 verification surface survives in the module.

No network: introspection is stubbed at the module seam.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
import jwt

from app import auth


def _token(claims: dict, key: str = "test-secret") -> str:
    payload = dict(claims)
    payload.setdefault("exp", datetime.now(timezone.utc) + timedelta(hours=1))
    return jwt.encode(payload, key, algorithm="HS256")


@pytest.fixture
def local_profile(monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", "test-secret")
    monkeypatch.setenv("GATEWAY_ENV", "local")
    return auth


@pytest.fixture
def production_profile(monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", "test-secret")
    monkeypatch.setenv("GATEWAY_ENV", "production")
    return auth


# --- local tokens are development-only -------------------------------------


def test_local_auth_enabled_in_local_and_test(monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", "test-secret")
    for env in ("local", "test"):
        monkeypatch.setenv("GATEWAY_ENV", env)
        assert auth.local_auth_enabled() is True


def test_local_auth_disabled_in_production_even_with_secret(production_profile):
    assert production_profile.local_auth_enabled() is False


def test_local_auth_disabled_without_secret(monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", None)
    monkeypatch.setenv("GATEWAY_ENV", "local")
    assert auth.local_auth_enabled() is False


def test_create_access_token_refused_outside_dev(production_profile):
    with pytest.raises(RuntimeError, match="Supabase"):
        production_profile.create_access_token({"sub": "u1", "email": "a@b.co"})


def test_local_token_rejected_in_production(production_profile):
    token = _token({"sub": "u1", "email": "a@b.co"})  # minted with the same secret
    assert production_profile.decode_token(token) is None


def test_local_token_accepted_in_local(local_profile):
    data = local_profile.decode_token(_token({"sub": "u1", "email": "a@b.co"}))
    assert data is not None
    assert data.user_id == "u1"
    assert data.issuer == "gateway:local"


def test_tampered_local_token_rejected(local_profile):
    token = _token({"sub": "u1", "email": "a@b.co"}, key="wrong-secret")
    assert local_profile.decode_token(token) is None


# --- Supabase tokens -------------------------------------------------------


def test_supabase_token_uses_introspected_subject(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "anon-key")
    monkeypatch.setattr(
        auth,
        "_introspect_supabase",
        lambda token: {"sub": "11111111-2222-3333-4444-555555555555", "email": "user@example.com"},
    )
    monkeypatch.setattr(auth, "_provision_supabase_user", lambda data: None)

    token = _token({"iss": "https://proj.supabase.co/auth/v1", "sub": "ignored", "email": "user@example.com"})
    data = auth.decode_token(token)

    assert data is not None
    # The owner id comes from GoTrue's answer, never from the unverified claim.
    assert data.user_id == "11111111-2222-3333-4444-555555555555"
    assert data.subject == "11111111-2222-3333-4444-555555555555"


def test_supabase_token_rejected_when_introspection_fails(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "anon-key")
    monkeypatch.setattr(auth, "_introspect_supabase", lambda token: None)

    token = _token({"iss": "https://proj.supabase.co/auth/v1", "sub": "x"})
    assert auth.decode_token(token) is None


def test_supabase_disabled_without_config(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    assert auth.supabase_auth_enabled() is False


# --- Auth0 is gone ---------------------------------------------------------


def test_no_auth0_surface_remains():
    assert not hasattr(auth, "AUTH0_DOMAIN")
    assert not hasattr(auth, "AUTH0_AUDIENCE")
    assert not hasattr(auth, "warm_auth0_jwks")
    assert not hasattr(auth, "_decode_auth0_token")


def test_rs256_tenant_token_is_not_trusted_without_supabase(local_profile, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    token = _token({"iss": "https://dev-tenant.us.auth0.com/", "sub": "auth0|abc"})
    assert local_profile.decode_token(token) is None


# --- password endpoints ----------------------------------------------------


def test_password_endpoints_refuse_outside_dev(monkeypatch, production_profile):
    from app.api.v1 import auth as auth_routes

    with pytest.raises(HTTPException) as exc:
        auth_routes._require_local_auth()
    assert exc.value.status_code == 503
    assert "Supabase" in exc.value.detail


def test_password_endpoints_work_in_local(monkeypatch, local_profile):
    from app.api.v1 import auth as auth_routes

    auth_routes._require_local_auth()  # does not raise


def test_operator_allowlist_fails_closed_when_empty(monkeypatch):
    monkeypatch.delenv("GATEWAY_OPERATOR_USER_IDS", raising=False)
    assert auth._operator_identities() == set()


def test_operator_allowlist_requires_exact_pairs(monkeypatch):
    monkeypatch.setenv(
        "GATEWAY_OPERATOR_USER_IDS",
        '[{"issuer": "https://proj.supabase.co/auth/v1", "subject": "abc"}]',
    )
    assert auth._operator_identities() == {("https://proj.supabase.co/auth/v1", "abc")}
