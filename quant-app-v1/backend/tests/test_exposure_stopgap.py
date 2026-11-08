from __future__ import annotations

import json

import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

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
        ("/ai-trading/log", "GET"),
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
        ("/llm/providers", "GET"),
    ],
)
@pytest.mark.asyncio
async def test_authenticated_private_routes_fail_closed_until_owner_isolation(path: str, method: str) -> None:
    response = await _request(path, token=_token(), method=method)
    assert response.status_code == 503
    assert response.json() == {"detail": "Private data unavailable until account isolation is enabled"}


@pytest.mark.asyncio
async def test_authenticated_strategies_are_owner_scoped_instead_of_gated() -> None:
    """The studio derives its owner per request, so it is no longer a shared store."""
    response = await _request("/strategies", token=_token())
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_authenticated_journal_is_owner_scoped_instead_of_gated() -> None:
    """The journal stamps and filters by owner, so it is no longer a shared store."""
    response = await _request("/journal", token=_token())
    assert response.status_code == 200
    assert response.json() == {"entries": []}


@pytest.mark.asyncio
async def test_authenticated_vault_is_owner_scoped_instead_of_gated(tmp_path, monkeypatch) -> None:
    """The vault stamps and filters by owner, so it is no longer a shared store."""
    from app.services import secrets_vault

    monkeypatch.setattr(secrets_vault, "_SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(secrets_vault, "_VAULT_FILE", tmp_path / "secrets.vault")
    monkeypatch.setattr(secrets_vault, "_VAULT_KEY_FILE", tmp_path / "secrets.vault.key")
    monkeypatch.setenv("GATEWAY_PROVIDER_KEY", "")

    response = await _request("/vault", token=_token())
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_authenticated_ai_trading_is_owner_scoped_instead_of_gated() -> None:
    """The AI trader resolves the caller's own config and book, so it is no longer a shared store."""
    response = await _request("/ai-trading", token=_token())
    assert response.status_code == 200
    assert response.json()["running"] is False
    assert response.json()["config"]["route"] == "paper"


@pytest.mark.asyncio
async def test_authenticated_portfolio_is_owner_scoped_instead_of_gated() -> None:
    """The paper book resolves `paper_<user.id>`, so it is no longer a shared store."""
    response = await _request("/portfolio", token=_token())
    assert response.status_code == 200
    assert response.json()["portfolio_id"] == "paper_stopgap-user"


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
    assert response.status_code == 410
    assert "Live broker sync was removed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_journal_live_sync_stays_unavailable_for_operator(monkeypatch) -> None:
    subject = "operator-user"
    monkeypatch.setenv(
        "GATEWAY_OPERATOR_USER_IDS",
        json.dumps([{"issuer": "gateway:local", "subject": subject}]),
    )
    response = await _request("/journal/sync-live", token=_token(subject), method="POST")
    assert response.status_code == 410


class _FakeWebSocket:
    """Frame-level stand-in for the handshake-only WebSocket handlers.

    The installed TestClient/httpx pair is incompatible (starlette passes
    ``app=`` to an httpx client that no longer accepts it), so the handlers are
    driven directly with exactly the frames a browser would send.
    """

    def __init__(
        self,
        *,
        query: dict[str, str] | None = None,
        frames: list[object] | None = None,
        text: list[str] | None = None,
    ) -> None:
        self.query_params = query or {}
        self.accepted = False
        self.sent: list[dict] = []
        self.closed: list[tuple[int, str]] = []
        self._frames = list(frames or [])
        self._text = list(text or [])

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed.append((code, reason))

    async def receive_json(self) -> object:
        if not self._frames:
            raise WebSocketDisconnect(1000)
        return self._frames.pop(0)

    async def receive_text(self) -> str:
        if not self._text:
            raise WebSocketDisconnect(1000)
        return self._text.pop(0)

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_websockets_reject_query_token_and_first_frame_fails_closed(monkeypatch) -> None:
    from app.api.main import websocket_trading
    from app.api.v1.portfolio import portfolio_websocket

    subject = "websocket-user"
    token = _token(subject)
    monkeypatch.delenv("GATEWAY_OPERATOR_USER_IDS", raising=False)

    # A token in the query string is refused before the socket is accepted.
    for handler in (websocket_trading, portfolio_websocket):
        socket = _FakeWebSocket(query={"token": token})
        await handler(socket)
        assert socket.accepted is False
        assert socket.closed == [(4001, "Token query parameters are not accepted")]

    # Any first frame that is not an authenticate message closes fail-closed.
    for handler in (websocket_trading, portfolio_websocket):
        socket = _FakeWebSocket(frames=[{"action": "subscribe", "symbol": "AAPL"}])
        await handler(socket)
        assert socket.accepted is True
        assert socket.sent == []
        assert socket.closed == [(4001, "Authentication required")]

    # A valid first frame authenticates trading; subscriptions echo the key.
    trading = _FakeWebSocket(
        frames=[{"type": "authenticate", "token": token}],
        text=[json.dumps({"action": "subscribe", "symbol": "AAPL", "tf": "1m"})],
    )
    await websocket_trading(trading)
    assert trading.sent == [
        {"type": "authenticated"},
        {"type": "subscribed", "symbol": "AAPL", "tf": "1m"},
    ]
    assert trading.closed == []  # a disconnect ends the loop without a close frame

    # The portfolio stream authenticates, then reports streaming as unavailable.
    stream = _FakeWebSocket(frames=[{"type": "authenticate", "token": token}])
    await portfolio_websocket(stream)
    assert stream.sent == [
        {
            "type": "error",
            "message": "Portfolio streaming is unavailable; poll GET /portfolio",
        }
    ]
    assert stream.closed == [(1013, "Streaming unavailable")]


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
