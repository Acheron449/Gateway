"""AI trading is owner-scoped per request (NFR-6).

The AI trader is no longer a shared store: signed-out calls are 401 from the
route dependency, config, decisions, the paper book and learned memory all
belong to the caller, another account's data is never returned, ownership never
comes from a request body, and a pre-ownership database is migrated with its
ownerless rows quarantined.
"""

from __future__ import annotations

import asyncio
import sqlite3
import typing

import httpx
import pytest
from fastapi.routing import APIRoute

from app import auth
from app.api.main import app
from app.api.v1 import ai_trading as ai_api
from app.auth import User
from app.services import ai_trading, database, journal_log


@pytest.fixture()
def trading_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "ai-trading.db")
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
async def test_signed_out_ai_trading_routes_answer_401_from_the_dependency() -> None:
    calls = [
        ("/ai-trading", "GET", None),
        ("/ai-trading", "PUT", {"symbols": ["AAPL"]}),
        ("/ai-trading/start", "POST", None),
        ("/ai-trading/stop", "POST", None),
        ("/ai-trading/cycle", "POST", None),
        ("/ai-trading/log", "GET", None),
        ("/ai-trading/memory/AAPL", "GET", None),
    ]
    for path, method, body in calls:
        response = await _request(path, method=method, body=body)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_signed_in_ai_trading_is_owner_scoped_instead_of_gated(trading_db) -> None:
    response = await _request("/ai-trading", token=_token("alice"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["running"] is False
    assert payload["config"]["symbols"] == ai_trading.DEFAULT_CONFIG["symbols"]
    assert payload["config"]["enabled"] is False
    assert payload["backtest_edge"] is None
    assert {row["closed"] for row in payload["journal_memory"].values()} == {0}


@pytest.mark.asyncio
async def test_config_writes_are_stamped_by_the_principal_not_the_body(trading_db) -> None:
    alice = {"symbols": ["AAPL"], "confidence_threshold": 0.7, "owner_id": "bob", "user_id": "bob"}
    saved = await _request("/ai-trading", token=_token("alice"), method="PUT", body=alice)
    assert saved.status_code == 200
    assert saved.json()["config"]["symbols"] == ["AAPL"]

    bob = await _request("/ai-trading", token=_token("bob"))
    assert bob.json()["config"]["symbols"] == ai_trading.DEFAULT_CONFIG["symbols"]

    with sqlite3.connect(database.DB_PATH) as conn:
        rows = conn.execute("SELECT owner_id FROM ai_trading_config").fetchall()
    assert rows == [("alice",)]


def test_config_and_memory_are_scoped_to_the_owner(trading_db) -> None:
    ai_trading.save_config("alice", {"symbols": ["AAPL"], "enabled": True})

    assert ai_trading.get_config("alice")["symbols"] == ["AAPL"]
    assert ai_trading.get_config("bob")["symbols"] == ai_trading.DEFAULT_CONFIG["symbols"]
    assert ai_trading.enabled_owners() == ["alice"]

    # A close on alice's book teaches alice only.
    buy = journal_log.log_fill(
        "fill-ai-a-buy", "AAPL", "buy", 2, 100.0, source="paper", owner_id="alice"
    )
    journal_log.log_fill(
        "fill-ai-a-sell", "AAPL", "sell", 2, 110.0, source="paper", owner_id="alice"
    )
    buy_b = journal_log.log_fill(
        "fill-ai-b-buy", "AAPL", "buy", 2, 100.0, source="paper", owner_id="bob"
    )
    journal_log.log_fill(
        "fill-ai-b-sell", "AAPL", "sell", 2, 90.0, source="paper", owner_id="bob"
    )
    assert buy and buy_b

    alice_memory = ai_trading.journal_memory("alice", "AAPL")
    bob_memory = ai_trading.journal_memory("bob", "AAPL")
    assert alice_memory == {"closed": 1, "wins": 1, "win_rate": 1.0, "pnl": 20.0}
    assert bob_memory == {"closed": 1, "wins": 0, "win_rate": 0.0, "pnl": -20.0}


def test_decision_log_is_owner_filtered(trading_db) -> None:
    ai_trading.log_decision("alice", "AAPL", "buy", 0.8, "momentum", price=100.0)
    ai_trading.log_decision("bob", "MSFT", "hold", 0.4, "below threshold", price=300.0)

    alice_rows = ai_trading.recent_log("alice")
    assert [row["symbol"] for row in alice_rows] == ["AAPL"]
    assert all(row["owner_id"] == "alice" for row in alice_rows)
    assert [row["symbol"] for row in ai_trading.recent_log("bob")] == ["MSFT"]


def test_cycle_only_touches_the_callers_book_and_log(trading_db, monkeypatch) -> None:
    ai_trading.save_config(
        "alice", {"symbols": ["AAPL"], "confidence_threshold": 0.5, "max_position_notional": 1000}
    )
    orders: list[tuple[str, str, str, int]] = []

    async def fake_evaluate(owner_id: str, symbol: str, config: dict) -> dict:
        return {"symbol": symbol, "signal": 1, "confidence": 1.0, "price": 100.0, "reason": "test"}

    def fake_order(owner_id: str, symbol: str, side: str, qty: int) -> dict:
        orders.append((owner_id, symbol, side, qty))
        return {"order_id": "o", "filled": True, "fill_price": 100.0}

    monkeypatch.setattr(ai_trading, "evaluate_symbol", fake_evaluate)
    monkeypatch.setattr(ai_trading, "_place_paper_order", fake_order)

    result = asyncio.run(ai_trading.run_cycle("alice"))
    assert result["route"] == "paper"
    assert result["decisions"][0]["action"] == "buy"
    assert orders == [("alice", "AAPL", "buy", 10)]

    assert [row["owner_id"] for row in ai_trading.recent_log("alice")] == ["alice"]
    assert ai_trading.recent_log("bob") == []
    assert database.get_portfolio("paper_alice")["user_id"] == "alice"
    assert database.get_portfolio("paper_bob") is None


def test_stopping_one_agent_leaves_the_other_owners_config_alone(trading_db) -> None:
    ai_trading.save_config("alice", {"enabled": True})
    ai_trading.save_config("bob", {"enabled": True})

    ai_trading.stop("alice")

    assert ai_trading.get_config("alice")["enabled"] is False
    assert ai_trading.get_config("bob")["enabled"] is True
    assert ai_trading.enabled_owners() == ["bob"]


def test_pre_ownership_log_is_migrated_and_legacy_rows_stay_invisible(trading_db) -> None:
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DROP TABLE IF EXISTS ai_trading_log")
        conn.execute(
            """
            CREATE TABLE ai_trading_log (
                id TEXT PRIMARY KEY,
                ts TEXT NOT NULL,
                symbol TEXT,
                action TEXT NOT NULL,
                confidence REAL,
                reason TEXT,
                price REAL,
                qty REAL,
                route TEXT,
                ok INTEGER DEFAULT 1,
                detail TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO ai_trading_log (id, ts, symbol, action, confidence, reason) "
            "VALUES ('legacy-decision', '2026-01-01T00:00:00+00:00', 'AAPL', 'hold', 0.1, 'old')"
        )
        conn.commit()

    # A legacy ownerless config file/row cannot exist in the new table, and the
    # legacy default book must never become the caller's book.
    database.create_portfolio("paper_default", "default_user")

    ai_trading._ensure_tables()

    with sqlite3.connect(database.DB_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_trading_log)")}
    assert "owner_id" in columns

    assert ai_trading.recent_log("alice") == []
    assert ai_trading.recent_log("bob") == []
    assert ai_trading.get_config("alice")["enabled"] is False
    assert database.get_portfolio("paper_default")["user_id"] == "default_user"
    assert database.get_portfolio("paper_alice") is None

    # Running alice's cycle resolves her own book, not the legacy default.
    with sqlite3.connect(database.DB_PATH) as conn:
        owner = conn.execute(
            "SELECT owner_id FROM ai_trading_log WHERE id = 'legacy-decision'"
        ).fetchone()
    assert owner == (None,)


def test_every_ai_trading_route_requires_a_principal() -> None:
    routes = [route for route in ai_api.router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 7
    for route in routes:
        hints = typing.get_type_hints(route.endpoint, include_extras=True)
        assert "user" in hints, route.path


def test_no_global_config_or_default_owner_survives() -> None:
    assert not hasattr(ai_trading, "_CONFIG_FILE")
    assert not hasattr(ai_trading, "DEFAULT_USER_ID")
    assert not hasattr(ai_trading, "paper_default")


def test_status_memory_and_backtest_edge_use_only_the_owners_receipts(trading_db) -> None:
    database.save_backtest_receipt(
        "run-alice",
        "alice",
        "succeeded",
        "AAPL",
        "1d",
        "hash-a",
        {"run_id": "run-alice"},
        {"trades": []},
        {"trades": 1, "total_return_pct": 10.0, "max_drawdown_pct": 2.0, "sharpe": 1.0},
    )
    database.save_backtest_receipt(
        "run-bob",
        "bob",
        "succeeded",
        "MSFT",
        "1d",
        "hash-b",
        {"run_id": "run-bob"},
        {"trades": []},
        {"trades": 1, "total_return_pct": -20.0, "max_drawdown_pct": 5.0, "sharpe": -1.0},
    )

    assert ai_trading.backtest_edge("alice") == pytest.approx(0.10)
    assert ai_trading.backtest_edge("bob") == pytest.approx(-0.20)
    assert ai_trading.backtest_edge("carol") is None
