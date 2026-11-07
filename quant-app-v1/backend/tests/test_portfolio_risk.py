"""Risk series are replayed from the portfolio's own ledger and fills.

The dashboard's numbers must come from recorded state, never a demo dataset:
these tests seed a real portfolio through the paper service and assert the
derived equity curve, drawdown path and metrics, plus owner scoping and the
narrow exception in ``PrivateDataGateMiddleware``.
"""

from __future__ import annotations

import httpx
import pytest

from app import auth
from app.api.main import app
from app.api.v1 import portfolio as portfolio_api
from app.models import OrderSide, OrderType
from app.services import database
from app.services.paper_portfolio import PaperPortfolioService
from app.services.portfolio_risk import build_portfolio_risk


@pytest.fixture()
def portfolios(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "risk.db")
    database.init_db()
    yield


def _seed_trading_portfolio(portfolio_id: str = "paper_risk_trader") -> None:
    """Buy 10 @ 100 then 10 @ 90 so the book dips below its deposit."""
    database.create_portfolio(portfolio_id, "risk_trader", initial_cash=100_000.0)
    service = PaperPortfolioService(portfolio_id)

    first = service.submit_order("AAPL", OrderSide.BUY, OrderType.MARKET, 10)
    service.execute_fill(first.id, "AAPL", OrderSide.BUY, 10, 100.0)

    second = service.submit_order("AAPL", OrderSide.BUY, OrderType.MARKET, 10)
    service.execute_fill(second.id, "AAPL", OrderSide.BUY, 10, 90.0)


def test_equity_and_drawdown_series_come_from_recorded_fills(portfolios) -> None:
    _seed_trading_portfolio()

    risk = build_portfolio_risk("paper_risk_trader")
    equity = risk["equity_curve"]
    drawdowns = risk["drawdown_curve"]

    assert len(equity) >= 3
    assert [point["time"] for point in equity] == sorted(point["time"] for point in equity)
    assert equity[0]["equity"] == pytest.approx(100_000.0)
    # 10 @ 100 then 10 @ 90: cash 98 100 plus 20 shares marked at 90.
    assert equity[-1]["equity"] == pytest.approx(99_900.0)
    assert equity[-1]["equity"] == pytest.approx(risk["equity"])

    assert len(drawdowns) == len(equity)
    assert drawdowns[0]["drawdown"] == 0.0
    assert min(point["drawdown"] for point in drawdowns) < 0
    assert risk["max_drawdown"] == pytest.approx(abs(min(point["drawdown"] for point in drawdowns)), abs=0.01)
    assert risk["current_drawdown"] == pytest.approx(risk["max_drawdown"], abs=0.01)

    assert risk["cash"] == pytest.approx(98_100.0)
    assert risk["open_positions"] == 1
    assert risk["positions"][0]["instrument_id"] == "AAPL"
    assert risk["positions"][0]["quantity"] == pytest.approx(20.0)
    assert risk["gross_exposure"] == pytest.approx(1_800.0 / 99_900.0, abs=1e-4)
    assert risk["concentration_risk"] == [{"symbol": "AAPL", "pct": 1.8}]
    assert risk["series_note"]


def test_empty_portfolio_reports_its_deposit_as_a_flat_curve(portfolios) -> None:
    database.create_portfolio("paper_idle", "idle_user", initial_cash=50_000.0)

    risk = build_portfolio_risk("paper_idle")

    assert [point["equity"] for point in risk["equity_curve"]] == [50_000.0]
    assert risk["max_drawdown"] == 0.0
    assert risk["current_drawdown"] == 0.0
    assert risk["open_positions"] == 0
    assert risk["gross_exposure"] == 0.0


@pytest.mark.asyncio
async def test_risk_endpoint_is_scoped_to_the_signed_in_owner(portfolios) -> None:
    alice = auth.User(id="alice", email="alice@example.test")
    bob = auth.User(id="bob", email="bob@example.test")
    await portfolio_api.get_portfolio_state(user=alice)

    alice_risk = await portfolio_api.get_portfolio_risk(user=alice)
    bob_risk = await portfolio_api.get_portfolio_risk(user=bob)

    assert alice_risk.portfolio_id == "paper_alice"
    assert bob_risk.portfolio_id == "paper_bob"
    assert alice_risk.portfolio_id != bob_risk.portfolio_id
    assert database.get_portfolio("paper_alice")["user_id"] == "alice"


async def _request(path: str, *, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


def _token(subject: str = "risk-http-user") -> str:
    return auth.create_access_token({"sub": subject, "email": "risk@example.test"})


@pytest.mark.asyncio
async def test_risk_route_requires_authentication(portfolios) -> None:
    response = await _request("/portfolio/risk")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_authenticated_risk_route_returns_its_own_series(portfolios) -> None:
    response = await _request("/portfolio/risk", token=_token())

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_id"] == "paper_risk-http-user"
    assert body["equity_curve"], "the dashboard needs at least one point to draw"
    assert body["drawdown_curve"]
    assert "series_note" in body


@pytest.mark.asyncio
async def test_only_the_risk_route_passes_the_private_data_gate(portfolios) -> None:
    token = _token()

    still_gated = await _request("/portfolio/history", token=token)
    allowed = await _request("/portfolio/risk", token=token)

    assert still_gated.status_code == 503
    assert allowed.status_code == 200
