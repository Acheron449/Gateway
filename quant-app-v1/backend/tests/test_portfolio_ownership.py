"""Portfolio routes are owner-scoped per request (NFR-6).

The HTTP surface is no longer a shared store: signed-out calls are 401 from the
route dependency, every handler resolves only ``paper_<user.id>``, another
account's book is the same 404 as a missing one, and a pre-ownership database is
migrated with its ownerless rows quarantined.
"""

from __future__ import annotations

import sqlite3
import typing

import httpx
import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from app import auth
from app.api.main import app
from app.api.v1 import portfolio as portfolio_api
from app.auth import User
from app.services import database


@pytest.fixture()
def portfolios(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "portfolios.db")
    database.init_db()
    yield


def _token(user_id: str) -> str:
    return auth.create_access_token({"sub": user_id, "email": f"{user_id}@example.test"})


async def _request(
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    body: dict | None = None,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=body)


@pytest.mark.asyncio
async def test_signed_out_portfolio_routes_answer_401_from_the_dependency() -> None:
    calls = [
        ("/portfolio", "GET", None),
        ("/portfolio/history", "GET", None),
        ("/portfolio/risk", "GET", None),
        ("/portfolio/market-status", "GET", None),
        (
            "/portfolio/orders",
            "POST",
            {"instrument": "AAPL", "side": "buy", "order_type": "market", "quantity": 1},
        ),
        ("/portfolio/paper_nobody", "GET", None),
    ]
    for path, method, body in calls:
        response = await _request(path, method=method, body=body)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_signed_in_portfolio_is_owner_scoped_instead_of_gated(portfolios) -> None:
    response = await _request("/portfolio", token=_token("alice"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio_id"] == "paper_alice"
    assert database.get_portfolio("paper_alice")["user_id"] == "alice"


@pytest.mark.asyncio
async def test_each_user_gets_an_owner_scoped_paper_portfolio(portfolios) -> None:
    alice = User(id="alice", email="alice@example.test")
    bob = User(id="bob", email="bob@example.test")

    alice_state = await portfolio_api.get_portfolio_state(user=alice)
    bob_state = await portfolio_api.get_portfolio_state(user=bob)

    assert alice_state.portfolio_id == "paper_alice"
    assert bob_state.portfolio_id == "paper_bob"
    assert database.get_portfolio("paper_alice")["user_id"] == "alice"
    assert database.get_portfolio("paper_bob")["user_id"] == "bob"


@pytest.mark.asyncio
async def test_portfolio_lookups_reject_another_owner(portfolios) -> None:
    alice = User(id="alice", email="alice@example.test")
    bob = User(id="bob", email="bob@example.test")
    await portfolio_api.get_portfolio_state(user=alice)

    with pytest.raises(HTTPException) as rejected:
        await portfolio_api.get_portfolio_detail("paper_alice", user=bob)
    assert rejected.value.status_code == 404

    # A missing resource and another account's resource are indistinguishable.
    with pytest.raises(HTTPException) as missing:
        await portfolio_api.get_portfolio_detail("paper_nobody", user=bob)
    assert missing.value.status_code == 404
    assert missing.value.detail == rejected.value.detail


@pytest.mark.asyncio
async def test_fill_simulation_only_ever_addresses_the_callers_book(
    portfolios, monkeypatch
) -> None:
    alice = User(id="alice", email="alice@example.test")
    bob = User(id="bob", email="bob@example.test")
    await portfolio_api.get_portfolio_state(user=alice)
    await portfolio_api.get_portfolio_state(user=bob)
    database.insert_paper_order(
        "alice-order", "paper_alice", None, "AAPL", "buy", "market", 1, None, None
    )

    calls: list[tuple[str, str]] = []

    def fake_try_fill(portfolio_id: str, order_id: str) -> None:
        calls.append((portfolio_id, order_id))
        return None

    monkeypatch.setattr(portfolio_api._fill_simulator, "try_fill_order", fake_try_fill)

    bob_result = await portfolio_api.simulate_fill_endpoint("alice-order", user=bob)
    assert bob_result.filled is False
    assert calls[-1] == ("paper_bob", "alice-order")

    alice_result = await portfolio_api.simulate_fill_endpoint("alice-order", user=alice)
    assert alice_result.filled is False
    assert calls[-1] == ("paper_alice", "alice-order")

    # The foreign attempt left the owner's working order untouched.
    open_orders = database.get_portfolio("paper_alice")["open_orders"]
    assert [order["id"] for order in open_orders] == ["alice-order"]


@pytest.mark.asyncio
async def test_pre_ownership_database_is_migrated_and_legacy_rows_stay_invisible(
    portfolios,
) -> None:
    path = database.DB_PATH
    with sqlite3.connect(path) as conn:
        # Recreate the pre-ownership shape: no user_id column at all.
        conn.execute("DROP TABLE portfolios")
        conn.execute(
            """
            CREATE TABLE portfolios (
                id TEXT PRIMARY KEY,
                cash REAL NOT NULL DEFAULT 0,
                equity REAL NOT NULL DEFAULT 0,
                buying_power REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO portfolios (id, cash, equity, buying_power, created_at, updated_at) "
            "VALUES ('legacy-book', 50000, 50000, 50000, '2026-01-01', '2026-01-01')"
        )
        conn.commit()

    database.init_db()

    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(portfolios)")}
    assert "user_id" in columns
    assert database.get_portfolio("legacy-book")["user_id"] is None

    alice = User(id="alice", email="alice@example.test")
    state = await portfolio_api.get_portfolio_state(user=alice)
    assert state.portfolio_id == "paper_alice"

    with pytest.raises(HTTPException) as missing:
        await portfolio_api.get_portfolio_detail("legacy-book", user=alice)
    assert missing.value.status_code == 404
    assert missing.value.detail == "Portfolio not found"


def test_every_portfolio_http_route_requires_a_principal() -> None:
    routes = [route for route in portfolio_api.router.routes if isinstance(route, APIRoute)]
    assert routes
    for route in routes:
        hints = typing.get_type_hints(route.endpoint, include_extras=True)
        assert "user" in hints, route.path


def test_no_shared_default_user_constant_survives() -> None:
    assert not hasattr(portfolio_api, "DEFAULT_USER_ID")
