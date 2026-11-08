"""Strategy Studio ownership (NFR-6, P2 isolation clause).

Every strategy route derives its owner from the verified principal. These tests
drive the handlers directly with two accounts and assert that one cannot list,
read, version, edit or delete the other's strategy, that legacy ownerless rows
stay quarantined, and that the private-data gate no longer answers 503 for the
surface.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, get_args, get_origin, get_type_hints

import httpx
import pytest
from fastapi import HTTPException

from app.api import main as api_main
from app.api.v1 import strategies as strategies_api
from app.auth import User, create_access_token
from app.models import StrategySpec
from app.services import database


@pytest.fixture()
def strategies_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "strategies.db")
    database.init_db()
    yield


def _user(user_id: str) -> User:
    return User(id=user_id, email=f"{user_id}@example.test", subject=user_id)


async def _create(user: User, name: str = "RSI Reversion", **overrides):
    request = strategies_api.StrategyCreateRequest(
        name=name,
        description=overrides.get("description", "Buy oversold RSI"),
        universe=overrides.get("universe", ["AAPL", "MSFT"]),
        timeframe=overrides.get("timeframe", "1d"),
        tags=overrides.get("tags", ["swing"]),
    )
    return await strategies_api.create_strategy(request, user=user)


@pytest.mark.asyncio
async def test_create_persists_the_owner_and_the_submitted_metadata(strategies_db) -> None:
    alice = _user("alice")
    created = await _create(alice)

    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM strategies WHERE id = ?", (created.id,)).fetchone()

    assert row["owner_id"] == "alice"
    assert json.loads(row["universe"]) == ["AAPL", "MSFT"]
    assert row["timeframe"] == "1d"
    assert created.universe == ["AAPL", "MSFT"]
    assert created.timeframe == "1d"


@pytest.mark.asyncio
async def test_list_only_returns_the_signed_in_accounts_strategies(strategies_db) -> None:
    alice = _user("alice")
    bob = _user("bob")
    alice_strategy = await _create(alice, "Alice momentum")
    await _create(bob, "Bob mean reversion")

    alice_list = await strategies_api.list_strategies(
        user=alice, status=None, tag=None, limit=50, offset=0
    )
    bob_list = await strategies_api.list_strategies(
        user=bob, status=None, tag=None, limit=50, offset=0
    )

    assert [strategy.id for strategy in alice_list] == [alice_strategy.id]
    assert [strategy.name for strategy in bob_list] == ["Bob mean reversion"]


@pytest.mark.asyncio
async def test_cross_owner_access_is_indistinguishable_from_missing(strategies_db) -> None:
    alice = _user("alice")
    bob = _user("bob")
    created = await _create(alice)
    alice_version = await strategies_api.get_strategy_version(created.id, 1, user=alice)
    spec = StrategySpec(**alice_version.spec)

    with pytest.raises(HTTPException) as missing:
        await strategies_api.get_strategy("does-not-exist", user=bob)
    assert missing.value.status_code == 404

    probes = [
        strategies_api.get_strategy(created.id, user=bob),
        strategies_api.list_strategy_versions(created.id, user=bob),
        strategies_api.get_strategy_version(created.id, 1, user=bob),
        strategies_api.update_strategy(
            created.id, strategies_api.StrategyUpdateRequest(name="Hijacked"), user=bob
        ),
        strategies_api.create_strategy_version(created.id, spec, user=bob),
        strategies_api.delete_strategy(created.id, user=bob),
    ]
    for probe in probes:
        with pytest.raises(HTTPException) as rejected:
            await probe
        assert rejected.value.status_code == 404
        assert rejected.value.detail == missing.value.detail

    # Alice's strategy is untouched by the rejected writes.
    still_alice = await strategies_api.get_strategy(created.id, user=alice)
    assert still_alice.name == "RSI Reversion"
    assert still_alice.version == 1


@pytest.mark.asyncio
async def test_rows_without_an_owner_stay_quarantined(strategies_db) -> None:
    alice = _user("alice")
    strategies_api._get_strategy_table()
    now = datetime.now(timezone.utc).isoformat()
    with database.get_connection() as conn:
        conn.execute(
            """INSERT INTO strategies
               (id, name, description, status, current_version, universe, timeframe, tags,
                created_at, updated_at)
               VALUES ('legacy', 'Legacy', '', 'draft', 1, '[]', '1h', '[]', ?, ?)""",
            (now, now),
        )
        conn.commit()

    assert (
        await strategies_api.list_strategies(
            user=alice, status=None, tag=None, limit=50, offset=0
        )
        == []
    )
    with pytest.raises(HTTPException) as rejected:
        await strategies_api.get_strategy("legacy", user=alice)
    assert rejected.value.status_code == 404


def test_every_strategy_route_derives_a_principal() -> None:
    routes = strategies_api.router.routes
    assert routes, "the strategies router must expose routes"
    for route in routes:
        annotation = get_type_hints(route.endpoint, include_extras=True).get("user")
        assert get_origin(annotation) is Annotated, route.path
        assert get_args(annotation)[0] is User, route.path


@pytest.mark.asyncio
async def test_strategies_require_a_principal_and_no_longer_hit_the_503_gate(
    strategies_db,
) -> None:
    transport = httpx.ASGITransport(app=api_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get("/strategies")
        assert anonymous.status_code == 401

        token = create_access_token({"sub": "alice", "email": "alice@example.test"})
        authorized = await client.get(
            "/strategies", headers={"Authorization": f"Bearer {token}"}
        )

    assert authorized.status_code == 200
    assert authorized.json() == []
