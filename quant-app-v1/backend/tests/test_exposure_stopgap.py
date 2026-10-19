from __future__ import annotations

import json

import httpx
import pytest

from app.api.main import app
from app import auth


async def _request(path: str, *, token: str | None = None, method: str = "GET") -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json={"active": True} if method != "GET" else None)


def _token(subject: str = "stopgap-user") -> str:
    return auth.create_access_token({"sub": subject, "email": "stopgap@example.test"})


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/portfolio", "GET"),
        ("/portfolio/orders", "POST"),
        ("/portfolio/orders/known-order/simulate-fill", "POST"),
        ("/strategies", "GET"),
        ("/strategies", "POST"),
        ("/journal", "GET"),
        ("/journal", "POST"),
        ("/ai-trading", "GET"),
        ("/ai-trading/start", "POST"),
        ("/risk/config", "GET"),
        ("/settings/providers", "GET"),
        ("/vault", "GET"),
        ("/llm/providers", "GET"),
    ],
)
@pytest.mark.asyncio
async def test_private_routes_require_authentication_before_shared_state(path: str, method: str) -> None:
    response = await _request(path, method=method)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/portfolio", "GET"),
        ("/portfolio/orders", "POST"),
        ("/portfolio/orders/known-order/simulate-fill", "POST"),
        ("/strategies", "GET"),
        ("/journal", "GET"),
        ("/ai-trading", "GET"),
        ("/vault", "GET"),
        ("/llm/providers", "GET"),
    ],
)
@pytest.mark.asyncio
async def test_authenticated_private_routes_fail_closed_until_owner_isolation(path: str, method: str) -> None:
    response = await _request(path, token=_token(), method=method)
    assert response.status_code == 503
    assert response.json() == {"detail": "Private data unavailable until account isolation is enabled"}


@pytest.mark.parametrize("configuration", [None, "", "not-json", "{}", "[]"])
@pytest.mark.asyncio
async def test_global_risk_and_provider_routes_deny_without_exact_operator_identity(monkeypatch, configuration) -> None:
    if configuration is None:
        monkeypatch.delenv("GATEWAY_OPERATOR_USER_IDS", raising=False)
    else:
        monkeypatch.setenv("GATEWAY_OPERATOR_USER_IDS", configuration)

    risk = await _request("/risk/config", token=_token())
    settings = await _request("/settings/providers", token=_token())
    assert risk.status_code == 403
    assert settings.status_code == 403
    assert risk.json() == settings.json() == {"detail": "Operator access required"}


@pytest.mark.asyncio
async def test_operator_routes_reject_wrong_issuer_and_duplicate_entries(monkeypatch) -> None:
    subject = "operator-user"
    monkeypatch.setenv(
        "GATEWAY_OPERATOR_USER_IDS",
        json.dumps([{"issuer": "https://untrusted.example/", "subject": subject}]),
    )
    wrong_issuer = await _request("/risk/config", token=_token(subject))
    assert wrong_issuer.status_code == 403

    monkeypatch.setenv(
        "GATEWAY_OPERATOR_USER_IDS",
        json.dumps([
            {"issuer": "gateway:local", "subject": subject},
            {"issuer": "gateway:local", "subject": subject},
        ]),
    )
    duplicate = await _request("/risk/config", token=_token(subject))
    assert duplicate.status_code == 403


@pytest.mark.asyncio
async def test_exact_operator_identity_can_reach_global_routes(monkeypatch) -> None:
    subject = "operator-user"
    monkeypatch.setenv(
        "GATEWAY_OPERATOR_USER_IDS",
        json.dumps([{"issuer": "gateway:local", "subject": subject}]),
    )
    risk = await _request("/risk/config", token=_token(subject))
    assert risk.status_code == 200


@pytest.mark.asyncio
async def test_journal_live_sync_stays_unavailable_for_authenticated_user() -> None:
    response = await _request("/journal/sync-live", token=_token(), method="POST")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_journal_live_sync_stays_unavailable_for_operator(monkeypatch) -> None:
    subject = "operator-user"
    monkeypatch.setenv(
        "GATEWAY_OPERATOR_USER_IDS",
        json.dumps([{"issuer": "gateway:local", "subject": subject}]),
    )
    response = await _request("/journal/sync-live", token=_token(subject), method="POST")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_portfolio_websocket_rejects_query_token_and_first_frame_fails_closed(monkeypatch) -> None:
    from starlette.testclient import TestClient

    subject = "websocket-user"
    token = _token(subject)
    monkeypatch.delenv("GATEWAY_OPERATOR_USER_IDS", raising=False)
    client = TestClient(app)
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/trading?token={token}"):
            pass
    with pytest.raises(Exception):
        with client.websocket_connect(f"/portfolio/stream?token={token}"):
            pass

    with client.websocket_connect("/ws/trading") as socket:
        socket.send_json({"type": "authenticate", "token": token})
        assert socket.receive_json() == {"type": "authenticated"}
        socket.send_json({"action": "subscribe", "symbol": "AAPL", "tf": "1m"})
        assert socket.receive_json() == {"type": "subscribed", "symbol": "AAPL", "tf": "1m"}

    with client.websocket_connect("/portfolio/stream") as socket:
        socket.send_json({"type": "authenticate", "token": token})
        assert socket.receive_json() == {
            "type": "error",
            "message": "Private data unavailable until account isolation is enabled",
        }


@pytest.mark.asyncio
async def test_kronos_runtime_install_is_disabled_and_status_is_sanitized(monkeypatch) -> None:
    monkeypatch.setenv("KRONOS_RUNTIME_INSTALL_ENABLED", "true")
    status = await _request("/forecast/kronos/install/status")
    install = await _request("/forecast/kronos/install?force=true&path=/tmp/attacker", method="POST")
    assert status.status_code == 200
    assert status.json() == {
        "enabled": False,
        "installed": False,
        "installing": False,
        "status": "disabled",
        "log_tail": "",
    }
    assert "repo_path" not in status.json()
    assert install.status_code == 503
    assert install.json() == {"detail": "Kronos runtime installation is disabled"}
