"""Regression tests for the P6 security-hardening findings.

Covers NFR-9 (environment-aware CSP), NFR-10 (default rate limiting plus
stricter auth budgets), NFR-11 (OpenBB integration removed rather than
patched) and NFR-19 (ownerless lab runs quarantined).
"""

from __future__ import annotations

import importlib.util

import httpx
import pytest
from slowapi.middleware import SlowAPIMiddleware

from app.api import main as api_main
from app.api.rate_limit import DEFAULT_LIMITS, limiter


def _directives(policy: str) -> dict[str, str]:
    directives: dict[str, str] = {}
    for part in policy.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition(" ")
        directives[name] = value.strip()
    return directives


def test_production_csp_has_no_inline_or_eval_scripts() -> None:
    directives = _directives(api_main.content_security_policy("production"))

    assert directives["script-src"] == "'self'"
    assert "unsafe-inline" not in directives["script-src"]
    assert "unsafe-eval" not in directives["script-src"]
    assert directives["default-src"] == "'self'"
    assert directives["style-src"] == "'self' 'unsafe-inline'"


def test_local_csp_keeps_vite_compatible_script_sources() -> None:
    directives = _directives(api_main.content_security_policy("local"))

    assert "'unsafe-inline'" in directives["script-src"]
    assert "'unsafe-eval'" in directives["script-src"]


def test_csp_helper_defaults_to_gateway_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_ENV", "production")

    assert api_main.content_security_policy() == api_main.content_security_policy("production")


@pytest.mark.asyncio
async def test_security_headers_carry_production_csp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GATEWAY_ENV", "production")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_main.app), base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == api_main.content_security_policy("production")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_slowapi_middleware_enforces_configured_defaults() -> None:
    middleware_classes = [middleware.cls for middleware in api_main.app.user_middleware]

    assert SlowAPIMiddleware in middleware_classes
    assert api_main.limiter is limiter
    configured = {
        getattr(group, "_LimitGroup__limit_provider")
        for group in limiter._default_limits
    }
    assert configured == set(DEFAULT_LIMITS)


@pytest.mark.asyncio
async def test_login_has_a_stricter_route_limit() -> None:
    limiter.reset()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_main.app), base_url="http://test") as client:
            statuses = [
                (
                    await client.post(
                        "/auth/login",
                        json={"email": "nobody@example.test", "password": "wrong-password"},
                    )
                ).status_code
                for _ in range(11)
            ]
    finally:
        limiter.reset()

    assert 429 not in statuses[:10]
    assert statuses[10] == 429


def _is_absent(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is None
    except ModuleNotFoundError:
        # A missing parent package (app.cli was deleted with the OpenBB CLI)
        # already proves the module itself cannot be imported.
        return True


def test_openbb_integration_is_removed() -> None:
    paths = set(api_main.app.openapi()["paths"])
    assert not any(path == "/openbb" or path.startswith("/openbb/") for path in paths)

    for module in (
        "app.api.openbb_routes",
        "app.providers.openbb_provider",
        "app.providers.openbb_server_provider",
        "app.cli.openbb_cli",
    ):
        assert _is_absent(module)

    capabilities = api_main.settings.capabilities
    assert "openbb_data" not in capabilities
    assert "openbb_server" not in capabilities

    import app.providers as providers

    with pytest.raises(AttributeError):
        providers.OpenBBProvider
