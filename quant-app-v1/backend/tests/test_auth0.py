"""Auth0 RS256 verification + dual-mode token dispatch tests.

Covers ``app.auth.decode_token`` and the request dependencies for both token
flavours:

* Auth0 access tokens verified against the tenant JWKS (issuer, audience,
  expiry, signature, key rotation, stale-cache behaviour).
* Local HS256 tokens keep working whether or not Auth0 mode is configured.
* Fail-closed startup when neither verification mode is configured.

No network access: ``_download_jwks`` (the httpx seam) is monkeypatched
throughout, so JWKS caching/rotation is exercised without leaving localhost.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt as jose_jwt

from app import auth

BACKEND_DIR = Path(__file__).resolve().parents[1]
DOMAIN = "dev-gateway-test.us.auth0.com"
ISSUER = f"https://{DOMAIN}/"
AUDIENCE = "https://gateway-api"


# --- helpers -----------------------------------------------------------------

def _b64u(value: int) -> str:
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()


def _make_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk_for(private_key, kid: str = "gw-test-key") -> dict:
    numbers = private_key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64u(numbers.n),
        "e": _b64u(numbers.e),
    }


def _claims(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": "auth0|gwuser1",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "email": "gwuser@example.com",
        "name": "Gateway User",
    }
    claims.update(overrides)
    return claims


def _sign(claims: dict, private_key, kid: str = "gw-test-key") -> str:
    return jose_jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def _reset_cache() -> None:
    with auth._jwks_lock:
        auth._jwks_cache["keys"] = []
        auth._jwks_cache["fetched_at"] = 0.0


@pytest.fixture
def rsa_key():
    return _make_key()


@pytest.fixture
def tenant(monkeypatch, rsa_key):
    """Auth0 mode ON, JWKS served from a local (fake) tenant."""
    monkeypatch.setattr(auth, "AUTH0_DOMAIN", DOMAIN)
    monkeypatch.setattr(auth, "AUTH0_AUDIENCE", None)
    jwk = _jwk_for(rsa_key)
    monkeypatch.setattr(auth, "_download_jwks", lambda: [copy.deepcopy(jwk)])
    _reset_cache()
    yield
    _reset_cache()


@pytest.fixture
def auth0_off(monkeypatch):
    """Auth0 mode OFF regardless of the ambient environment."""
    monkeypatch.setattr(auth, "AUTH0_DOMAIN", "")
    monkeypatch.setattr(auth, "AUTH0_AUDIENCE", None)
    _reset_cache()
    yield
    _reset_cache()


# --- Auth0 happy path --------------------------------------------------------

def test_auth0_token_accepted(tenant, rsa_key):
    token = _sign(_claims(), rsa_key)
    data = auth.decode_token(token)
    assert data is not None
    assert data.user_id == "auth0|gwuser1"
    assert data.email == "gwuser@example.com"
    assert data.name == "Gateway User"
    assert data.exp > datetime.now(timezone.utc)


def test_auth0_token_without_email_claim_falls_back_to_sub(tenant, rsa_key):
    claims = _claims()
    claims.pop("email")
    data = auth.decode_token(_sign(claims, rsa_key))
    assert data is not None
    assert data.email == "auth0|gwuser1"


def test_auth0_audience_checked_when_configured(monkeypatch, tenant, rsa_key):
    monkeypatch.setattr(auth, "AUTH0_AUDIENCE", "https://other-api")
    assert auth.decode_token(_sign(_claims(), rsa_key)) is None
    monkeypatch.setattr(auth, "AUTH0_AUDIENCE", AUDIENCE)
    assert auth.decode_token(_sign(_claims(), rsa_key)) is not None


def test_auth0_expired_token_rejected(tenant, rsa_key):
    past = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp())
    assert auth.decode_token(_sign(_claims(exp=past), rsa_key)) is None


def test_auth0_bad_signature_rejected(tenant, rsa_key):
    attacker = _make_key()
    # Sign with a stranger key while claiming the tenant's kid.
    assert auth.decode_token(_sign(_claims(), attacker)) is None


def test_auth0_wrong_issuer_dispatches_to_local_and_fails(auth0_off, rsa_key):
    # Auth0 not configured: an RS256 tenant token must never be trusted.
    assert auth.decode_token(_sign(_claims(), rsa_key)) is None


def test_auth0_issuer_mismatch_within_configured_tenant(tenant, rsa_key):
    claims = _claims(iss="https://attacker-tenant.us.auth0.com/")
    assert auth.decode_token(_sign(claims, rsa_key)) is None


def test_malformed_token_rejected(tenant):
    assert auth.decode_token("not-a-jwt") is None
    assert auth.decode_token("") is None


# --- JWKS cache / rotation ---------------------------------------------------

def test_unknown_kid_forces_jwks_refresh(monkeypatch, rsa_key):
    """Auth0 rotates signing keys — an unseen kid must trigger one refetch."""
    monkeypatch.setattr(auth, "AUTH0_DOMAIN", DOMAIN)
    old_key = _make_key()
    new_key = _make_key()
    responses = [[_jwk_for(old_key, "old-key")], [_jwk_for(new_key, "new-key")]]
    monkeypatch.setattr(auth, "_download_jwks", lambda: responses.pop(0) if responses else [])
    _reset_cache()

    token = _sign(_claims(), new_key, kid="new-key")
    data = auth.decode_token(token)
    assert data is not None and data.user_id == "auth0|gwuser1"
    _reset_cache()


def test_jwks_outage_serves_stale_keys(monkeypatch, rsa_key):
    """A JWKS refresh failure must not lock signed-in users out."""
    monkeypatch.setattr(auth, "AUTH0_DOMAIN", DOMAIN)
    jwk = _jwk_for(rsa_key)
    monkeypatch.setattr(auth, "_download_jwks", lambda: [copy.deepcopy(jwk)])
    _reset_cache()

    assert auth.decode_token(_sign(_claims(), rsa_key)) is not None  # primes cache

    def _boom():
        raise RuntimeError("network down")

    monkeypatch.setattr(auth, "_download_jwks", _boom)
    with auth._jwks_lock:  # age the cache past the TTL so a refresh is due
        auth._jwks_cache["fetched_at"] = 0.0
    assert auth.decode_token(_sign(_claims(), rsa_key)) is not None
    _reset_cache()


# --- Local HS256 regression --------------------------------------------------

def test_local_token_works_with_auth0_enabled(tenant):
    token = auth.create_access_token({"sub": "user-1", "email": "local@example.com"})
    data = auth.decode_token(token)
    assert data is not None
    assert data.user_id == "user-1"
    assert data.email == "local@example.com"


def test_local_token_works_with_auth0_disabled(auth0_off):
    token = auth.create_access_token({"sub": "user-2", "email": "local2@example.com"})
    data = auth.decode_token(token)
    assert data is not None
    assert data.user_id == "user-2"


def test_tampered_local_token_rejected(auth0_off):
    token = auth.create_access_token({"sub": "user-3", "email": "x@example.com"})
    forged = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    assert auth.decode_token(forged) is None


# --- Request dependencies ----------------------------------------------------

def test_get_current_user_accepts_auth0_token(tenant, rsa_key):
    token = _sign(_claims(), rsa_key)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = asyncio.run(auth.get_current_user(credentials))
    assert user.id == "auth0|gwuser1"
    assert user.email == "gwuser@example.com"
    assert user.name == "Gateway User"


def test_get_current_user_rejects_bad_token(tenant, rsa_key):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth.get_current_user(credentials))
    assert exc.value.status_code == 401


def test_get_current_user_optional_returns_none_for_bad_token(tenant):
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage")
    assert asyncio.run(auth.get_current_user_optional(credentials)) is None


# --- Fail-closed startup -----------------------------------------------------

def test_import_fails_without_any_verification_mode():
    env = {k: v for k, v in os.environ.items() if k not in ("JWT_SECRET_KEY", "AUTH0_DOMAIN", "AUTH0_AUDIENCE")}
    result = subprocess.run(
        [sys.executable, "-c", "import app.auth"],
        cwd=BACKEND_DIR,
        env={**env, "PYTHONPATH": "."},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0, "app.auth must refuse to start with no verification mode"
    assert "JWT_SECRET_KEY" in result.stderr


def test_local_auth_disabled_when_secret_missing(monkeypatch):
    monkeypatch.setattr(auth, "SECRET_KEY", None)
    assert auth.local_auth_enabled() is False
    with pytest.raises(RuntimeError):
        auth.create_access_token({"sub": "x", "email": "x@example.com"})


def test_password_endpoints_503_in_auth0_only_mode(monkeypatch):
    """Auth0-only deployment: register/login/refresh refuse politely."""
    from app.api.v1 import auth as auth_api

    monkeypatch.setattr(auth, "SECRET_KEY", None)
    for handler in (auth_api.register, auth_api.login, auth_api.refresh):
        if handler is auth_api.register:
            payload = auth_api.RegisterRequest(email="a@b.co", password="password1")
        elif handler is auth_api.login:
            payload = auth_api.LoginRequest(email="a@b.co", password="password1")
        else:
            payload = auth.User(id="u1", email="a@b.co")
        with pytest.raises(HTTPException) as exc:
            handler(payload)
        assert exc.value.status_code == 503
        assert "Auth0" in exc.value.detail
