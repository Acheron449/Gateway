from __future__ import annotations

import pytest
from decimal import Decimal

from app.models import Order, OrderSide, OrderStatus, OrderType
from app.services.database import create_portfolio, get_portfolio
from app.services.paper_portfolio import PaperPortfolioService, PortfolioEvent, EventType
from app.services.risk_engine import RiskEngine, RiskConfig, RiskCheckResult


TEST_PORTFOLIO_ID = "test_portfolio_123"
TEST_USER_ID = "test_user"


def setup_module():
    create_portfolio(TEST_PORTFOLIO_ID, TEST_USER_ID, 100000.0)


def teardown_module():
    import sqlite3
    from pathlib import Path
    DB_PATH = Path(__file__).resolve().parents[3] / "quant_app.db"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM portfolio_events WHERE portfolio_id = ?", (TEST_PORTFOLIO_ID,))
        cur.execute("DELETE FROM cash_ledger WHERE portfolio_id = ?", (TEST_PORTFOLIO_ID,))
        cur.execute("DELETE FROM fills WHERE order_id IN (SELECT id FROM paper_orders WHERE portfolio_id = ?)", (TEST_PORTFOLIO_ID,))
        cur.execute("DELETE FROM paper_orders WHERE portfolio_id = ?", (TEST_PORTFOLIO_ID,))
        cur.execute("DELETE FROM positions WHERE portfolio_id = ?", (TEST_PORTFOLIO_ID,))
        cur.execute("DELETE FROM portfolios WHERE id = ?", (TEST_PORTFOLIO_ID,))
        conn.commit()


class TestPaperPortfolioEventSourcing:
    def test_submit_and_acknowledge_order(self):
        service = PaperPortfolioService(TEST_PORTFOLIO_ID)
        order = service.submit_order(
            instrument_id="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=10,
        )
        assert order.id is not None
        assert order.status == OrderStatus.PENDING_NEW

        service.acknowledge_order(order.id)
        portfolio = get_portfolio(TEST_PORTFOLIO_ID)
        open_orders = [o for o in portfolio["open_orders"] if o["id"] == order.id]
        assert len(open_orders) == 1
        assert open_orders[0]["status"] == OrderStatus.ACCEPTED.value

    def test_execute_fill_updates_position_and_cash(self):
        service = PaperPortfolioService(TEST_PORTFOLIO_ID)
        order = service.submit_order(
            instrument_id="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=5,
            limit_price=300.0,
        )
        service.acknowledge_order(order.id)

        fill = service.execute_fill(
            order_id=order.id,
            instrument_id="MSFT",
            side=OrderSide.BUY,
            qty=5,
            price=300.0,
            commission=1.0,
        )
        assert fill.quantity == 5
        assert fill.price == 300.0

        portfolio = service.get_current_state()
        positions = portfolio["positions"]
        msft_pos = next((p for p in positions if p["instrument_id"] == "MSFT"), None)
        assert msft_pos is not None
        assert msft_pos["quantity"] == 5
        assert msft_pos["avg_cost"] == 300.0
        assert msft_pos["market_value"] == 1500.0

        assert portfolio["cash"] == 100000.0 - (300.0 * 5 + 1.0)
        assert portfolio["equity"] == portfolio["cash"] + 1500.0

    def test_sell_fill_calculates_realized_pnl(self):
        service = PaperPortfolioService(TEST_PORTFOLIO_ID)
        portfolio_before = service.get_current_state()
        cash_before = portfolio_before["cash"]

        order = service.submit_order(
            instrument_id="MSFT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=2,
        )
        service.acknowledge_order(order.id)

        fill = service.execute_fill(
            order_id=order.id,
            instrument_id="MSFT",
            side=OrderSide.SELL,
            qty=2,
            price=310.0,
            commission=0.5,
        )

        portfolio = service.get_current_state()
        msft_pos = next((p for p in portfolio["positions"] if p["instrument_id"] == "MSFT"), None)
        assert msft_pos is not None
        assert msft_pos["quantity"] == 3
        assert msft_pos["realized_pnl"] == 20.0

        assert portfolio["cash"] == cash_before + (310.0 * 2 - 0.5)

    def test_reconstruct_portfolio_from_event_log(self):
        service = PaperPortfolioService(TEST_PORTFOLIO_ID)
        original = service.get_current_state()

        events = get_portfolio(TEST_PORTFOLIO_ID)  # This will have events from above
        reconstructed = service.reconstruct_portfolio()

        assert reconstructed is not None
        assert reconstructed["cash"] == original["cash"]
        assert reconstructed["equity"] == original["equity"]
        assert len(reconstructed["positions"]) == len(original["positions"])

    def test_apply_event_pure_function(self):
        service = PaperPortfolioService(TEST_PORTFOLIO_ID)

        event = PortfolioEvent(
            event_type=EventType.CASH_UPDATE,
            event_data={
                "cash": 50000.0,
                "equity": 50000.0,
                "buying_power": 50000.0,
                "amount": -50000.0,
                "type": "withdrawal",
                "ref_id": None,
                "ref_type": None,
            },
            timestamp="2024-01-01T00:00:00+00:00",
        )
        service.apply_event(event)

        portfolio = get_portfolio(TEST_PORTFOLIO_ID)
        assert portfolio["cash"] == 50000.0


class TestRiskEngine:
    def setup_method(self):
        self.config = RiskConfig(
            max_concentration_instrument=0.10,
            max_concentration_sector=0.20,
            max_gross_exposure=2.0,
            max_net_exposure=1.0,
            daily_loss_limit_pct=0.05,
            enable_margin=False,
            blocked_instruments=["GME", "AMC"],
            event_blackout_minutes=15,
        )
        self.engine = RiskEngine(self.config)

    def test_buying_power_check_passes_with_sufficient_cash(self):
        from app.services.database import create_portfolio
        test_id = "test_risk_1"
        create_portfolio(test_id, "user", 100000.0)

        order = Order(
            id="test",
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            account_id=test_id,
        )
        result, violations = self.engine.check_order(test_id, order, 150.0)
        assert result == RiskCheckResult.PASSED
        assert len(violations) == 0

    def test_buying_power_check_rejects_insufficient_cash(self):
        from app.services.database import create_portfolio
        test_id = "test_risk_2"
        create_portfolio(test_id, "user", 1000.0)

        order = Order(
            id="test",
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            account_id=test_id,
        )
        result, violations = self.engine.check_order(test_id, order, 150.0)
        assert result == RiskCheckResult.REJECTED
        assert any(v.check == "buying_power" for v in violations)

    def test_concentration_limit_rejects_over_concentrated_order(self):
        from app.services.database import create_portfolio, update_position
        test_id = "test_risk_3"
        create_portfolio(test_id, "user", 100000.0)
        update_position(test_id, "AAPL", 100, 150.0, 15000.0, 0.0, 0.0)

        order = Order(
            id="test",
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            account_id=test_id,
        )
        result, violations = self.engine.check_order(test_id, order, 150.0)
        assert result == RiskCheckResult.REJECTED
        assert any(v.check == "concentration_instrument" for v in violations)

    def test_blocked_instrument_rejected(self):
        from app.services.database import create_portfolio
        test_id = "test_risk_4"
        create_portfolio(test_id, "user", 100000.0)

        order = Order(
            id="test",
            instrument="GME",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            account_id=test_id,
        )
        result, violations = self.engine.check_order(test_id, order, 150.0)
        assert result == RiskCheckResult.REJECTED
        assert any(v.check == "instrument_restriction" for v in violations)

    def test_gross_exposure_limit(self):
        from app.services.database import create_portfolio, update_position
        test_id = "test_risk_5"
        create_portfolio(test_id, "user", 100000.0)
        update_position(test_id, "AAPL", 100, 150.0, 15000.0, 0.0, 0.0)
        update_position(test_id, "MSFT", 100, 300.0, 30000.0, 0.0, 0.0)

        order = Order(
            id="test",
            instrument="GOOGL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            account_id=test_id,
        )
        result, violations = self.engine.check_order(test_id, order, 2000.0)
        assert result == RiskCheckResult.REJECTED
        assert any(v.check == "gross_exposure" for v in violations)

    def test_kill_switch_activated_on_daily_loss(self):
        from app.services.database import create_portfolio, update_position
        test_id = "test_risk_6"
        create_portfolio(test_id, "user", 100000.0)
        update_position(test_id, "AAPL", 100, 200.0, 10000.0, -6000.0, 0.0)

        order = Order(
            id="test",
            instrument="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            account_id=test_id,
        )
        result, violations = self.engine.check_order(test_id, order, 300.0)
        assert result == RiskCheckResult.KILL_SWITCH
        assert self.engine.is_kill_switch_active()

    def test_kill_switch_blocks_all_orders(self):
        self.engine.activate_kill_switch("Test kill switch")

        from app.services.database import create_portfolio
        test_id = "test_risk_7"
        create_portfolio(test_id, "user", 100000.0)

        order = Order(
            id="test",
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            account_id=test_id,
        )
        result, violations = self.engine.check_order(test_id, order, 150.0)
        assert result == RiskCheckResult.KILL_SWITCH

    def test_reset_kill_switch(self):
        self.engine.activate_kill_switch("Test")
        assert self.engine.is_kill_switch_active()

        self.engine.reset_kill_switch()
        assert not self.engine.is_kill_switch_active()
        assert self.engine.get_kill_switch_reason() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])