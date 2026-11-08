"""Trade Journal ownership (NFR-6, P2 isolation clause).

Every journal route derives its owner from the verified principal, and the
paper-fill auto-logger attributes entries to the portfolio's owner. These tests
drive the handlers directly with two accounts, assert that cross-owner access is
indistinguishable from a missing id, that legacy ownerless rows stay invisible,
and that the private-data gate no longer answers 503 for the surface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, get_args, get_origin, get_type_hints

import httpx
import pytest
from fastapi import HTTPException

from app.api import main as api_main
from app.api.v1 import journal as journal_api
from app.auth import User, create_access_token
from app.services import database, journal_log


@pytest.fixture()
def journal_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "journal.db")
    database.init_db()
    yield


def _user(user_id: str) -> User:
    return User(id=user_id, email=f"{user_id}@example.test", subject=user_id)


async def _create(user: User, symbol: str = "AAPL"):
    return await journal_api.create_journal_entry(
        journal_api.JournalEntryCreate(
            symbol=symbol,
            side="buy",
            quantity=10,
            entry_price=100.0,
            hypothesis="Breakout above the range high",
            entry_context="Volume expansion",
            tags=["swing"],
        ),
        user=user,
    )


async def _list(user: User):
    return await journal_api.list_journal_entries(
        user=user,
        status=None,
        source=None,
        symbol=None,
        start_date=None,
        end_date=None,
        tag=None,
        limit=100,
        offset=0,
    )


@pytest.mark.asyncio
async def test_create_stamps_the_owner(journal_db) -> None:
    created = await _create(_user("alice"))

    with database.get_connection() as conn:
        row = conn.execute("SELECT owner_id, symbol FROM journal_entries WHERE id = ?", (created.id,)).fetchone()

    assert row["owner_id"] == "alice"
    assert row["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_list_and_stats_are_scoped_to_the_signed_in_account(journal_db) -> None:
    alice = _user("alice")
    bob = _user("bob")
    await _create(alice, "AAPL")

    alice_entries = (await _list(alice))["entries"]
    bob_entries = (await _list(bob))["entries"]
    alice_stats = await journal_api.get_journal_stats(user=alice, source=None)
    bob_stats = await journal_api.get_journal_stats(user=bob, source=None)

    assert [entry["symbol"] for entry in alice_entries] == ["AAPL"]
    assert bob_entries == []
    assert alice_stats.total_trades == 1
    assert bob_stats.total_trades == 0


@pytest.mark.asyncio
async def test_cross_owner_access_is_indistinguishable_from_missing(journal_db) -> None:
    alice = _user("alice")
    bob = _user("bob")
    created = await _create(alice)

    with pytest.raises(HTTPException) as missing:
        await journal_api.get_journal_entry("does-not-exist", user=bob)
    assert missing.value.status_code == 404

    probes = [
        journal_api.get_journal_entry(created.id, user=bob),
        journal_api.update_journal_entry(
            created.id, journal_api.JournalEntryUpdate(lessons="hijacked"), user=bob
        ),
        journal_api.close_trade(
            created.id, journal_api.JournalEntryUpdate(exit_price=90.0), user=bob
        ),
        journal_api.delete_journal_entry(created.id, user=bob),
    ]
    for probe in probes:
        with pytest.raises(HTTPException) as rejected:
            await probe
        assert rejected.value.status_code == 404
        assert rejected.value.detail == missing.value.detail

    still_alice = await journal_api.get_journal_entry(created.id, user=alice)
    assert still_alice.status == "open"
    assert still_alice.lessons is None


@pytest.mark.asyncio
async def test_paper_fill_auto_logging_stamps_and_scopes_the_owner(journal_db) -> None:
    fill_id = "fill-owner-check"
    assert journal_log.log_fill(
        fill_id,
        "MSFT",
        "buy",
        5,
        200.0,
        source="paper",
        owner_id="alice",
    )

    assert [entry["symbol"] for entry in (await _list(_user("alice")))["entries"]] == ["MSFT"]
    assert (await _list(_user("bob")))["entries"] == []
    # A fill with no owner cannot be attributed and is refused rather than orphaned.
    assert journal_log.log_fill("fill-orphan", "TSLA", "buy", 1, 10.0, source="paper") is None


@pytest.mark.asyncio
async def test_rows_without_an_owner_stay_quarantined(journal_db) -> None:
    alice = _user("alice")
    journal_api._get_journal_table()
    now = datetime.now(timezone.utc).isoformat()
    with database.get_connection() as conn:
        conn.execute(
            """INSERT INTO journal_entries
               (id, symbol, side, quantity, entry_price, entry_time, hypothesis,
                entry_context, tags, status, source, created_at, updated_at)
               VALUES ('legacy-journal', 'AAPL', 'buy', 1, 10, ?, 'legacy', '', '[]',
                       'open', 'manual', ?, ?)""",
            (now, now, now),
        )
        conn.commit()

    assert (await _list(alice))["entries"] == []
    with pytest.raises(HTTPException) as rejected:
        await journal_api.get_journal_entry("legacy-journal", user=alice)
    assert rejected.value.status_code == 404


def test_every_journal_route_derives_a_principal() -> None:
    routes = journal_api.router.routes
    assert routes, "the journal router must expose routes"
    for route in routes:
        annotation = get_type_hints(route.endpoint, include_extras=True).get("user")
        assert get_origin(annotation) is Annotated, route.path
        assert get_args(annotation)[0] is User, route.path


@pytest.mark.asyncio
async def test_journal_requires_a_principal_and_no_longer_hits_the_503_gate(journal_db) -> None:
    transport = httpx.ASGITransport(app=api_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        anonymous = await client.get("/journal")
        assert anonymous.status_code == 401

        token = create_access_token({"sub": "alice", "email": "alice@example.test"})
        authorized = await client.get("/journal", headers={"Authorization": f"Bearer {token}"})

    assert authorized.status_code == 200
    assert authorized.json() == {"entries": []}
