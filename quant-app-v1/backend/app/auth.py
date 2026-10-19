"""JWT Authentication middleware for FastAPI.

Two token flavours share one dependency chain, dispatched by the (unverified)
``iss`` claim:

* **Local HS256** tokens signed with ``JWT_SECRET_KEY`` — issued by
  ``POST /auth/register`` and ``POST /auth/login``.
* **Auth0 RS256** access tokens from the tenant configured via
  ``AUTH0_DOMAIN`` (plus optional ``AUTH0_AUDIENCE``), verified against the
  tenant's JWKS over https — never against a caller-supplied key.

Config is failure-closed: the process refuses to start when no verification
mode is configured at all (neither ``JWT_SECRET_KEY`` nor ``AUTH0_DOMAIN``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from loguru import logger
from pydantic import BaseModel

# JWT Configuration — failure-closed: no default secret. Auth0-only
# deployments may skip JWT_SECRET_KEY as long as AUTH0_DOMAIN is set.
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
AUTH0_DOMAIN = os.getenv("AUTH0_DOMAIN", "").strip().rstrip("/")
AUTH0_AUDIENCE = os.getenv("AUTH0_AUDIENCE", "").strip() or None
if not SECRET_KEY and not AUTH0_DOMAIN:
    raise RuntimeError(
        "JWT_SECRET_KEY must be set in the environment — refusing to start with a default secret "
        "(or set AUTH0_DOMAIN for an Auth0-only deployment)"
    )

ALGORITHM = "HS256"
AUTH0_ALGORITHM = "RS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Auth0 JWKS cache: warmed at startup, refreshed at most once per TTL, with an
# immediate re-fetch when an unknown `kid` shows up (signing-key rotation).
_JWKS_TTL_SECONDS = 600.0
_jwks_lock = threading.Lock()
_jwks_cache: dict = {"keys": [], "fetched_at": 0.0}

security = HTTPBearer(auto_error=False)


def local_auth_enabled() -> bool:
    """True when local password login can issue tokens (JWT_SECRET_KEY set)."""
    return bool(SECRET_KEY)


def auth0_enabled() -> bool:
    """True when an Auth0 tenant is configured for RS256 verification."""
    return bool(AUTH0_DOMAIN)


def _auth0_issuer() -> str:
    return f"https://{AUTH0_DOMAIN}/"


class TokenData(BaseModel):
    user_id: str
    email: str
    exp: datetime
    name: str | None = None


class User(BaseModel):
    id: str
    email: str
    name: str | None = None


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a local HS256 JWT access token."""
    if not SECRET_KEY:
        raise RuntimeError(
            "Local password auth is disabled (JWT_SECRET_KEY unset) — tokens are issued by Auth0"
        )
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> TokenData | None:
    """Decode and validate a JWT — local HS256 or Auth0 RS256.

    Dispatch is by the *unverified* ``iss`` claim: only tokens whose issuer
    matches the configured Auth0 tenant take the Auth0 path, everything else
    the local path. A forged issuer still fails RS256 verification, and a
    forged local token fails the HMAC check, so neither can cross over.
    """
    try:
        claims = jwt.get_unverified_claims(token)
    except Exception as exc:  # malformed token — fail closed
        logger.debug("Token rejected before dispatch: {}", exc)
        return None
    if not isinstance(claims, dict):
        return None
    issuer = claims.get("iss")
    if (
        AUTH0_DOMAIN
        and isinstance(issuer, str)
        and issuer.rstrip("/") == f"https://{AUTH0_DOMAIN}"
    ):
        return _decode_auth0_token(token)
    if _supabase_conf() is not None and _looks_like_supabase(issuer):
        # Supabase Auth access token — verify by introspection at GoTrue.
        return _decode_supabase_token(token, claims)
    return _decode_local_token(token)


def _decode_local_token(token: str) -> TokenData | None:
    if not SECRET_KEY:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        exp_timestamp: int = payload.get("exp")
        if user_id is None or email is None:
            return None
        exp = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        return TokenData(user_id=user_id, email=email, exp=exp, name=payload.get("name"))
    except (JWTError, TypeError, ValueError, OSError):
        return None


# --- Supabase Auth ---------------------------------------------------------
# Third token flavour: access tokens issued by Supabase Auth (GoTrue) for the
# project in SUPABASE_URL. Instead of holding the project JWT secret, the
# backend verifies by introspection — GET /auth/v1/user only answers 200 for
# tokens GoTrue itself accepts (signature, expiry, bans), so the secret stays
# dashboard-only. Verified results are cached briefly so a hot endpoint pays
# one outbound call per token rather than one per request; failures are
# cached even more briefly so junk bearer tokens cannot turn into a stream of
# outbound calls.

_SB_INTROSPECT_TTL = 60.0
_SB_NEGATIVE_TTL = 10.0
_SB_CACHE_MAX = 512
_sb_cache: dict[str, tuple[float, TokenData | None]] = {}
_sb_lock = threading.Lock()


def _supabase_conf() -> tuple[str, str] | None:
    """(project url, publishable key) when Supabase Auth is configured."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = (os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY") or "").strip()
    if not url or not key:
        return None
    return url, key


def _looks_like_supabase(issuer: object) -> bool:
    """True for Supabase token issuers (legacy 'supabase' or project URL).

    Local HS256 tokens carry no `iss`, so they never reach the outbound
    introspection call — only tokens claiming to come from Supabase do.
    """
    if not isinstance(issuer, str) or not issuer:
        return False
    return issuer == "supabase" or ".supabase.co" in issuer


def _introspect_supabase(token: str) -> dict | None:
    conf = _supabase_conf()
    if conf is None:
        return None
    url, key = conf
    try:
        response = httpx.get(
            f"{url}/auth/v1/user",
            headers={"apikey": key, "Authorization": f"Bearer {token}"},
            timeout=3.0,
        )
    except Exception as exc:  # network trouble — fail closed
        logger.warning("Supabase token introspection failed: {}", exc)
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _provision_supabase_user(data: TokenData) -> None:
    """Create the gateway profile row for a Supabase user on first sight.

    Best-effort: a failed profile write must not reject an otherwise valid
    sign-in, but it is logged loudly because preference writes need the row.
    """
    try:
        from app.services.database import ensure_user

        ensure_user(user_id=data.user_id, email=data.email, name=data.name)
    except Exception as exc:
        logger.warning(
            "Could not provision gateway_users row for Supabase user {}: {}",
            data.user_id,
            exc,
        )


def _decode_supabase_token(token: str, claims: dict) -> TokenData | None:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _sb_lock:
        cached = _sb_cache.get(digest)
        if cached is not None and cached[0] > now:
            return cached[1]

    payload = _introspect_supabase(token)
    data: TokenData | None = None
    if payload:
        sub = payload.get("sub") or payload.get("id")
        if sub:
            # GoTrue validated exp when it answered 200; prefer the claim's
            # value so the per-request expiry check keeps working offline of
            # GoTrue, falling back to the introspected payload.
            exp_raw = claims.get("exp") or payload.get("exp")
            try:
                exp = datetime.fromtimestamp(float(exp_raw), tz=timezone.utc)
            except (TypeError, ValueError, OSError):
                exp = datetime.now(timezone.utc) + timedelta(seconds=3600)
            metadata = payload.get("user_metadata") if isinstance(payload.get("user_metadata"), dict) else {}
            email = payload.get("email") or claims.get("email") or f"{sub}@supabase.local"
            name = metadata.get("name") or payload.get("name") or claims.get("name")
            data = TokenData(user_id=str(sub), email=str(email), exp=exp, name=name)

    ttl = _SB_INTROSPECT_TTL if data is not None else _SB_NEGATIVE_TTL
    with _sb_lock:
        _sb_cache[digest] = (now + ttl, data)
        if len(_sb_cache) > _SB_CACHE_MAX:
            for key in [k for k, (expiry, _) in _sb_cache.items() if expiry <= now]:
                _sb_cache.pop(key, None)
            while len(_sb_cache) > _SB_CACHE_MAX:
                _sb_cache.pop(next(iter(_sb_cache)), None)

    if data is not None:
        _provision_supabase_user(data)
    return data


def _download_jwks() -> list[dict]:
    """Fetch the tenant JWKS over https (test seam for the cache layer)."""
    url = f"https://{AUTH0_DOMAIN}/.well-known/jwks.json"
    response = httpx.get(url, timeout=5.0, follow_redirects=True)
    response.raise_for_status()
    payload = response.json()
    keys = payload.get("keys") if isinstance(payload, dict) else None
    return [key for key in (keys or []) if isinstance(key, dict)]


def _fetch_jwks(force: bool = False) -> list[dict]:
    """Return JWKS keys, cached for _JWKS_TTL_SECONDS.

    A failed refresh serves stale keys when any are cached (a transient JWKS
    outage should not lock every signed-in user out) and fails closed when
    nothing is cached.
    """
    with _jwks_lock:
        cached = list(_jwks_cache["keys"])
        age = time.monotonic() - float(_jwks_cache["fetched_at"])
        if not force and cached and age < _JWKS_TTL_SECONDS:
            return cached
        try:
            keys = _download_jwks()
        except Exception as exc:
            if cached:
                logger.warning("Auth0 JWKS refresh failed; serving cached keys: {}", exc)
                return cached
            logger.warning("Auth0 JWKS fetch failed: {}", exc)
            return []
        if keys:
            _jwks_cache["keys"] = keys
            _jwks_cache["fetched_at"] = time.monotonic()
        return keys


def _select_signing_key(keys: list[dict], kid: str | None) -> dict | None:
    usable = [
        key
        for key in keys
        if key.get("kty") == "RSA" and key.get("alg", AUTH0_ALGORITHM) == AUTH0_ALGORITHM
    ]
    if kid is None:
        return usable[0] if len(usable) == 1 else None
    for key in usable:
        if key.get("kid") == kid:
            return key
    return None


def _auth0_signing_key(token: str) -> dict | None:
    try:
        headers = jwt.get_unverified_headers(token)
    except Exception:
        return None
    kid = headers.get("kid") if isinstance(headers, dict) else None
    key = _select_signing_key(_fetch_jwks(), kid)
    if key is None:
        # Unknown kid almost always means Auth0 rotated its signing keys.
        key = _select_signing_key(_fetch_jwks(force=True), kid)
    return key


def _decode_auth0_token(token: str) -> TokenData | None:
    signing_key = _auth0_signing_key(token)
    if signing_key is None:
        logger.debug("Auth0 token rejected: no matching JWKS key")
        return None
    options: dict = {"require": ["exp", "iss", "sub"]}
    audience = AUTH0_AUDIENCE
    if not audience:
        # python-jose refuses tokens carrying `aud` when no audience is passed.
        # Without AUTH0_AUDIENCE configured we skip only the audience check —
        # RS256 signature, issuer and expiry are still enforced.
        options["verify_aud"] = False
        audience = None
    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[AUTH0_ALGORITHM],
            audience=audience,
            issuer=_auth0_issuer(),
            options=options,
        )
    except JWTError as exc:
        logger.debug("Auth0 token rejected: {}", exc)
        return None
    except Exception as exc:  # network/parse trouble — fail closed to 401
        logger.warning("Auth0 token verification failed: {}", exc)
        return None

    sub = payload.get("sub")
    if not sub:
        return None
    # Prefer verified email claims, fall back so the UI always has an id.
    email = payload.get("email") or payload.get("preferred_username") or str(sub)
    try:
        exp = datetime.fromtimestamp(float(payload.get("exp")), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return TokenData(user_id=str(sub), email=str(email), exp=exp, name=payload.get("name"))


async def warm_auth0_jwks() -> None:
    """Pre-fetch the Auth0 JWKS at startup so the first sign-in isn't latency-bound."""
    if not AUTH0_DOMAIN:
        return
    try:
        keys = await asyncio.to_thread(_fetch_jwks, True)
        logger.info("Auth0 JWKS loaded: {} signing key(s) for {}", len(keys), AUTH0_DOMAIN)
    except Exception as exc:
        logger.warning("Auth0 JWKS warmup failed: {}", exc)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
) -> User:
    """Get current authenticated user from JWT token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_data = decode_token(credentials.credentials)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token_data.exp < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return User(id=token_data.user_id, email=token_data.email, name=token_data.name)


async def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
) -> User | None:
    """Get current user if authenticated, otherwise return None."""
    if credentials is None:
        return None
    token_data = decode_token(credentials.credentials)
    if token_data is None or token_data.exp < datetime.now(timezone.utc):
        return None
    return User(id=token_data.user_id, email=token_data.email, name=token_data.name)


# Dependency for protected routes
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]


async def private_data_unavailable(user: CurrentUser) -> None:
    del user
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Private data unavailable until account isolation is enabled")


def _operator_identities() -> set[tuple[str, str]]:
    raw = os.getenv("GATEWAY_OPERATOR_USER_IDS", "")
    if not raw.strip():
        return set()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    identities: list[tuple[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict) or set(item) != {"issuer", "subject"}:
            return set()
        issuer, subject = item["issuer"], item["subject"]
        if not isinstance(issuer, str) or not issuer.strip() or not isinstance(subject, str) or not subject.strip():
            return set()
        identities.append((issuer, subject))
    return set() if len(identities) != len(set(identities)) else set(identities)

async def require_operator(user: CurrentUser) -> User:
    if (user.issuer, user.subject or user.id) not in _operator_identities():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator access required")
    return user
