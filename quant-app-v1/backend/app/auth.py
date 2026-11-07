"""JWT authentication for FastAPI.

One identity provider: **Supabase Auth (GoTrue)**. Access tokens are verified
by introspection — ``GET {SUPABASE_URL}/auth/v1/user`` only answers 200 for
tokens GoTrue itself accepts (signature, expiry, bans) — so the project JWT
secret never has to leave the Supabase dashboard.

Local HS256 tokens exist for development and tests only: they are issued and
accepted when ``GATEWAY_ENV`` is ``local`` or ``test``. Every other profile
refuses to issue them and requires Supabase to be configured, because a token
this process minted is not evidence of a real account.

Verified identity is always ``(issuer, subject)``; the subject is the Supabase
user id, which is the only value any route may treat as ownership.
"""

from __future__ import annotations

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
import jwt
from jwt import InvalidTokenError
from loguru import logger
from pydantic import BaseModel

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Profiles that may use email/password sign-in against this service.
LOCAL_AUTH_ENVS = {"local", "test"}

security = HTTPBearer(auto_error=False)


def gateway_env() -> str:
    """Current profile, read at call time so tests can vary it."""
    return (os.getenv("GATEWAY_ENV", "local") or "local").strip().lower()


def local_auth_enabled() -> bool:
    """True only when this profile may issue local password tokens."""
    return bool(SECRET_KEY) and gateway_env() in LOCAL_AUTH_ENVS


class TokenData(BaseModel):
    user_id: str
    email: str
    exp: datetime
    name: str | None = None
    issuer: str
    subject: str


class User(BaseModel):
    id: str
    email: str
    name: str | None = None
    issuer: str = "gateway:local"
    subject: str | None = None


# --- Supabase Auth ---------------------------------------------------------
# Verified results are cached briefly so a hot endpoint pays one outbound call
# per token rather than one per request; failures are cached even more briefly
# so junk bearer tokens cannot turn into a stream of outbound calls.

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


def supabase_auth_enabled() -> bool:
    """True when token introspection can be attempted."""
    return _supabase_conf() is not None


# Fail closed outside the development profiles: a deployment with neither
# Supabase nor a local secret has no way to authenticate anybody.
if not local_auth_enabled() and _supabase_conf() is None and gateway_env() not in LOCAL_AUTH_ENVS:
    raise RuntimeError(
        "No token verifier is configured — set SUPABASE_URL and SUPABASE_KEY. "
        "Local password auth is only available when GATEWAY_ENV is local or test."
    )


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Issue a local HS256 token. Development and tests only."""
    if not local_auth_enabled():
        raise RuntimeError(
            "Local password auth is disabled — sign in with Supabase Auth"
        )
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> TokenData | None:
    """Decode and validate an access token.

    Supabase tokens are verified by introspection. Everything else is treated
    as a local token, which only verifies in the development profiles.
    """
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception as exc:  # malformed token — fail closed
        logger.debug("Token rejected before dispatch: {}", exc)
        return None
    if not isinstance(claims, dict):
        return None
    if _supabase_conf() is not None and _looks_like_supabase(claims.get("iss")):
        return _decode_supabase_token(token, claims)
    return _decode_local_token(token)


def _decode_local_token(token: str) -> TokenData | None:
    if not local_auth_enabled():
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        exp_timestamp: int = payload.get("exp")
        if user_id is None or email is None:
            return None
        exp = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        return TokenData(
            user_id=user_id,
            email=email,
            exp=exp,
            name=payload.get("name"),
            issuer="gateway:local",
            subject=user_id,
        )
    except (InvalidTokenError, TypeError, ValueError, OSError):
        return None


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

    conf = _supabase_conf()
    if conf is None:
        return None
    url, _key = conf
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
            data = TokenData(
                user_id=str(sub),
                email=str(email),
                exp=exp,
                name=name,
                issuer=f"{url}/auth/v1",
                subject=str(sub),
            )

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


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
) -> User:
    """Get current authenticated user from the bearer token."""
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
    return User(
        id=token_data.user_id,
        email=token_data.email,
        name=token_data.name,
        issuer=token_data.issuer,
        subject=token_data.subject,
    )


async def get_current_user_optional(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
) -> User | None:
    """Get current user if authenticated, otherwise return None."""
    if credentials is None:
        return None
    token_data = decode_token(credentials.credentials)
    if token_data is None or token_data.exp < datetime.now(timezone.utc):
        return None
    return User(
        id=token_data.user_id,
        email=token_data.email,
        name=token_data.name,
        issuer=token_data.issuer,
        subject=token_data.subject,
    )


# Dependency for protected routes
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]


async def private_data_unavailable(user: CurrentUser) -> None:
    """Authenticate before denying routes that still use shared private state."""
    del user
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Private data unavailable until account isolation is enabled",
    )


PrivateDataUnavailable = Annotated[None, Depends(private_data_unavailable)]


def _operator_identities() -> set[tuple[str, str]]:
    """Parse exact issuer/subject pairs; absent or ambiguous config denies."""
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
    if len(identities) != len(set(identities)):
        return set()
    return set(identities)


async def require_operator(user: CurrentUser) -> User:
    if (user.issuer, user.subject or user.id) not in _operator_identities():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator access required")
    return user


OperatorUser = Annotated[User, Depends(require_operator)]
PrivilegedDataUnavailable = Annotated[None, Depends(private_data_unavailable)]
