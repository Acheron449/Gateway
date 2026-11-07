"""Portfolio routes derive ownership from the verified principal (NFR-6).

The HTTP surface is still behind ``PrivateDataGateMiddleware`` (503), so these
tests drive the handlers directly with distinct ``CurrentUser`` values and
assert that each account resolves to its own book.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.v1 import portfolio as portfolio_api
from app.auth import User
from app.services import database


@pytest.fixture()
def portfolios(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "portfolios.db")
    database.init_db()
    yield


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


def test_no_shared_default_user_constant_survives() -> None:
    assert not hasattr(portfolio_api, "DEFAULT_USER_ID")
