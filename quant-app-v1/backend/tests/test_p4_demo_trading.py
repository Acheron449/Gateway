"""P4 exit gate: one admission path, durable kill switch, no broker code."""

from __future__ import annotations

import pathlib
import re

import pytest

from app.models import OrderSide, OrderType
from app.services import database, kill_switch
from app.services.order_admission import admit_order
from app.services.paper_portfolio import PaperPortfolioService
from app.services.risk_engine import RiskCheckResult, RiskConfig, RiskEngine


@pytest.fixture()
def portfolio(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "p4-demo.db")
    database.init_db()
    kill_switch.reset(reset_by="test")
    database.create_portfolio("p-test", "owner-1", 1_000.0)
    # The default risk profile caps a single instrument at 10% of equity, which
    # would reject the reservation scenarios before they reach the reservation.
    # These tests are about cash accounting, so the concentration cap is opened
    # up; the kill-switch tests below do not need it.
    relaxed = RiskEngine(
        RiskConfig(
            max_concentration_instrument=1.0,
            max_concentration_sector=1.0,
            max_concentration_asset_class=1.0,
            max_gross_exposure=10.0,
            max_net_exposure=10.0,
            daily_loss_limit_pct=0.9,
        )
    )
    monkeypatch.setattr("app.services.order_admission.get_risk_engine", lambda: relaxed)
    yield "p-test"
    kill_switch.reset(reset_by="test")


def _buy(qty: float, price: float = 100.0):
    return admit_order(
        portfolio_id="p-test",
        instrument="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=qty,
        limit_price=price,
        price=price,
    )


def test_admission_reserves_cash_before_persisting(portfolio):
    decision = _buy(4)
    assert decision.accepted is True
    assert decision.simulated is True
    state = database.get_portfolio(portfolio)
    assert len(state["open_orders"]) == 1
    assert state["buying_power"] == pytest.approx(600.0, abs=0.01)
    assert float(state["open_orders"][0]["reserved_amount"]) == pytest.approx(400.0)


def test_second_order_cannot_spend_reserved_cash(portfolio):
    assert _buy(4).accepted is True
    second = _buy(7)
    assert second.accepted is False
    assert second.status == "rejected"
    state = database.get_portfolio(portfolio)
    assert len(state["open_orders"]) == 1, "a rejected order must not be persisted"


def test_kill_switch_blocks_before_any_write(portfolio):
    kill_switch.activate("manual halt", activated_by="test")
    decision = _buy(1)
    assert decision.accepted is False
    assert decision.status == "blocked"
    assert "manual halt" in (decision.reason or "")
    assert database.get_portfolio(portfolio)["open_orders"] == []


def test_kill_switch_is_durable_across_engine_instances(portfolio):
    kill_switch.activate("daily loss", activated_by="test")
    fresh_engine = RiskEngine()
    # Kill switch is checked by the risk engine without any shared memory.
    from app.models import Order

    order = Order(
        id="x",
        instrument="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=1,
        limit_price=100.0,
        account_id=portfolio,
    )
    verdict, _ = fresh_engine.check_order(portfolio, order, 100.0)
    assert verdict == RiskCheckResult.KILL_SWITCH

    kill_switch.reset(reset_by="test")
    verdict, _ = RiskEngine().check_order(portfolio, order, 100.0)
    assert verdict == RiskCheckResult.PASSED


def test_fill_releases_the_reservation(portfolio):
    decision = _buy(4)
    assert decision.accepted
    service = PaperPortfolioService(portfolio)
    service.execute_fill(
        order_id=decision.order_id,
        instrument_id="AAPL",
        side=OrderSide.BUY,
        qty=4,
        price=100.0,
        commission=0.0,
    )
    state = database.get_portfolio(portfolio)
    assert database.get_open_reserved_total(portfolio) == pytest.approx(0.0)
    assert state["buying_power"] == pytest.approx(state["cash"], abs=0.01)


def test_admission_requires_a_price_when_market_data_is_down(portfolio, monkeypatch):
    monkeypatch.setattr(
        "app.services.market_data.get_quote_triplet_sync", lambda symbol: None, raising=False
    )
    decision = admit_order(
        portfolio_id="p-test",
        instrument="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=1,
    )
    assert decision.accepted is False
    assert decision.status == "unavailable"


FORBIDDEN_IMPORTS = (
    "from alpaca.trading",
    "import alpaca.trading",
    "from alpaca.broker",
    "import alpaca.broker",
    "ib_insync",
    "import ibapi",
    "from ibapi",
    "robinhood",
    "binance.client",
    "coinbase.wallet",
)


def test_no_broker_execution_code_remains():
    """FR-T7: no code path can construct a broker order request."""
    app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders: list[str] = []
    for path in app_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in FORBIDDEN_IMPORTS:
            if pattern in text:
                offenders.append(f"{path.relative_to(app_root)}: {pattern}")
    assert offenders == []


def test_broker_modules_are_gone():
    app_root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for name in ("services/broker_service.py", "services/alpaca_live.py", "api/v1/live.py", "trading_orchestrator.py"):
        assert not (app_root / name).exists(), f"{name} must not ship in a demo-only product"
