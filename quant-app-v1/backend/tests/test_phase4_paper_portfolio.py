from __future__ import annotations

import pytest
from uuid import uuid4

from app.models import Order, OrderSide, OrderStatus, OrderType
from app.services.database import create_portfolio, get_portfolio, update_position
from app.services.paper_portfolio import PaperPortfolioService, PortfolioEvent, EventType
from app.services.risk_engine import RiskEngine, RiskConfig, RiskCheckResult


@pytest.fixture
def portfolio_id() -> str:
    """Create a unique portfolio ID for each test."""
    return f"test_portfolio_{uuid4().hex[:8]}"


@pytest.fixture
def test_portfolio(portfolio_id: str) -> str:
    """Create a test portfolio and clean up after."""
    create_portfolio(portfolio_id, "test_user", 100000.0)
    yield portfolio_id
    # Cleanup
    import sqlite3
    from pathlib import Path
    DB_PATH = Path(__file__).resolve().parents[2] / "quant_app.db"
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM portfolio_events WHERE portfolio_id = ?", (portfolio_id,))
        cur.execute("DELETE FROM cash_ledger WHERE portfolio_id = ?", (portfolio_id,))
        cur.execute("DELETE FROM fills WHERE order_id IN (SELECT id FROM paper_orders WHERE portfolio_id = ?)", (portfolio_id,))
        cur.execute("DELETE FROM paper_orders WHERE portfolio_id = ?", (portfolio_id,))
        cur.execute("DELETE FROM positions WHERE portfolio_id = ?", (portfolio_id,))
        cur.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))
        conn.commit()


class TestPaperPortfolioEventSourcing:
    def test_submit_and_acknowledge_order(self, test_portfolio: str):
        service = PaperPortfolioService(test_portfolio)
        order = service.submit_order(
            instrument_id="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=10,
        )
        assert order.id is not None
        assert order.status == OrderStatus.PENDING_NEW

        service.acknowledge_order(order.id)
        portfolio = get_portfolio(test_portfolio)
        open_orders = [o for o in portfolio["open_orders"] if o["id"] == order.id]
        assert len(open_orders) == 1
        assert open_orders[0]["status"] == OrderStatus.ACCEPTED.value

    def test_execute_fill_updates_position_and_cash(self, test_portfolio: str):
        service = PaperPortfolioService(test_portfolio)
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

    def test_sell_fill_calculates_realized_pnl(self, test_portfolio: str):
        service = PaperPortfolioService(test_portfolio)
        # First buy some shares
        buy_order = service.submit_order(
            instrument_id="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=5,
        )
        service.acknowledge_order(buy_order.id)
        service.execute_fill(
            order_id=buy_order.id,
            instrument_id="MSFT",
            side=OrderSide.BUY,
            qty=5,
            price=300.0,
            commission=1.0,
        )

        portfolio_before = service.get_current_state()
        cash_before = portfolio_before["cash"]

        # Now sell 2 shares
        sell_order = service.submit_order(
            instrument_id="MSFT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            qty=2,
        )
        service.acknowledge_order(sell_order.id)

        fill = service.execute_fill(
            order_id=sell_order.id,
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

    def test_reconstruct_portfolio_from_event_log(self, test_portfolio: str):
        # Create a fresh portfolio for reconstruction test
        from app.services.database import append_portfolio_event
        from datetime import datetime, timezone
        
        # Clear any existing events for this portfolio
        import sqlite3
        from pathlib import Path
        DB_PATH = Path(__file__).resolve().parents[2] / "quant_app.db"
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM portfolio_events WHERE portfolio_id = ?", (test_portfolio,))
            cur.execute("DELETE FROM cash_ledger WHERE portfolio_id = ?", (test_portfolio,))
            cur.execute("DELETE FROM fills WHERE order_id IN (SELECT id FROM paper_orders WHERE portfolio_id = ?)", (test_portfolio,))
            cur.execute("DELETE FROM paper_orders WHERE portfolio_id = ?", (test_portfolio,))
            cur.execute("DELETE FROM positions WHERE portfolio_id = ?", (test_portfolio,))
            # Reset portfolio to initial state
            cur.execute("UPDATE portfolios SET cash=100000.0, equity=100000.0, buying_power=100000.0 WHERE id=?", (test_portfolio,))
            conn.commit()
        
        # Insert events manually to simulate a history
        order_id = f"test_order_{uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        
        # ORDER_SUBMITTED event
        append_portfolio_event(test_portfolio, "OrderSubmitted", {
            "order_id": order_id,
            "instrument_id": "AAPL",
            "side": "buy",
            "type": "market",
            "qty": 10,
            "limit_price": None,
            "stop_price": None,
            "strategy_version_id": None,
        }, 1)
        
        # ORDER_ACKNOWLEDGED event
        append_portfolio_event(test_portfolio, "OrderAcknowledged", {
            "order_id": order_id,
        }, 2)
        
        # FILL event
        append_portfolio_event(test_portfolio, "Fill", {
            "order_id": order_id,
            "instrument_id": "AAPL",
            "side": "buy",
            "qty": 10,
            "price": 150.0,
            "commission": 0.5,
            "timestamp": now,
            "liquidity": None,
        }, 3)
        
        # Now reconstruct from events
        service = PaperPortfolioService(test_portfolio)
        reconstructed = service.reconstruct_portfolio()
        
        assert reconstructed is not None
        # After buying 10 shares at $150 with $0.50 commission: cash = 100000 - 1500.5 = 98499.5
        assert reconstructed["cash"] == 98499.5
        assert reconstructed["equity"] == 98499.5 + 1500.0  # cash + market value
        assert len(reconstructed["positions"]) == 1
        assert reconstructed["positions"][0]["instrument_id"] == "AAPL"
        assert reconstructed["positions"][0]["quantity"] == 10

    def test_apply_event_pure_function(self, test_portfolio: str):
        service = PaperPortfolioService(test_portfolio)

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

        portfolio = get_portfolio(test_portfolio)
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

    def test_buying_power_check_passes_with_sufficient_cash(self, test_portfolio: str):
        order = Order(
            id="test",
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            account_id=test_portfolio,
        )
        result, violations = self.engine.check_order(test_portfolio, order, 150.0)
        assert result == RiskCheckResult.PASSED
        assert len(violations) == 0

    def test_buying_power_check_rejects_insufficient_cash(self):
        # Create portfolio with low cash - use a different ID
        test_id = f"test_risk_low_cash_{uuid4().hex[:8]}"
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

    def test_concentration_limit_rejects_over_concentrated_order(self, test_portfolio: str):
        # Create portfolio with existing AAPL position
        update_position(test_portfolio, "AAPL", 100, 150.0, 15000.0, 0.0, 0.0)

        order = Order(
            id="test",
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            account_id=test_portfolio,
        )
        result, violations = self.engine.check_order(test_portfolio, order, 150.0)
        assert result == RiskCheckResult.REJECTED
        assert any(v.check == "concentration_instrument" for v in violations)

    def test_blocked_instrument_rejected(self, test_portfolio: str):
        order = Order(
            id="test",
            instrument="GME",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=10,
            account_id=test_portfolio,
        )
        result, violations = self.engine.check_order(test_portfolio, order, 150.0)
        assert result == RiskCheckResult.REJECTED
        assert any(v.check == "instrument_restriction" for v in violations)

    def test_gross_exposure_limit(self, test_portfolio: str):
        update_position(test_portfolio, "AAPL", 100, 150.0, 15000.0, 0.0, 0.0)
        update_position(test_portfolio, "MSFT", 100, 300.0, 30000.0, 0.0, 0.0)

        order = Order(
            id="test",
            instrument="GOOGL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=100,
            account_id=test_portfolio,
        )
        result, violations = self.engine.check_order(test_portfolio, order, 2000.0)
        assert result == RiskCheckResult.REJECTED
        assert any(v.check == "gross_exposure" for v in violations)

    def test_kill_switch_activated_on_daily_loss(self, test_portfolio: str):
        update_position(test_portfolio, "AAPL", 100, 200.0, 10000.0, -6000.0, 0.0)

        order = Order(
            id="test",
            instrument="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            account_id=test_portfolio,
        )
        result, violations = self.engine.check_order(test_portfolio, order, 300.0)
        assert result == RiskCheckResult.KILL_SWITCH
        assert self.engine.is_kill_switch_active()

    def test_kill_switch_blocks_all_orders(self, test_portfolio: str):
        self.engine.activate_kill_switch("Test kill switch")

        order = Order(
            id="test",
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=1,
            account_id=test_portfolio,
        )
        result, violations = self.engine.check_order(test_portfolio, order, 150.0)
        assert result == RiskCheckResult.KILL_SWITCH

    def test_reset_kill_switch(self):
        self.engine.activate_kill_switch("Test")
        assert self.engine.is_kill_switch_active()

        self.engine.reset_kill_switch()
        assert not self.engine.is_kill_switch_active()
        assert self.engine.get_kill_switch_reason() is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])