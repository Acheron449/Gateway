from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from app.services.risk_engine import RiskEngine, RiskConfig, get_risk_engine
from app.services.database import create_portfolio, get_portfolio, update_portfolio_cash, update_position
from app.models import OrderSide


class KillSwitchTrigger(str, Enum):
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MANUAL = "manual"
    EXPOSURE_LIMIT = "exposure_limit"
    CONCENTRATION_LIMIT = "concentration_limit"
    SYSTEM_ERROR = "system_error"
    CHAOS_TEST = "chaos_test"


class TestStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class KillSwitchEvent:
    trigger: KillSwitchTrigger
    reason: str
    timestamp: datetime
    portfolio_id: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChaosTestScenario:
    name: str
    description: str
    trigger: KillSwitchTrigger
    setup_fn: str
    expected_activation_time_seconds: float
    cleanup_fn: str | None = None


@dataclass(frozen=True, slots=True)
class ChaosTestResult:
    scenario_name: str
    status: TestStatus
    activation_time_ms: float | None
    expected_time_ms: float
    error_message: str | None
    details: dict


class KillSwitchTester:
    """Automated kill switch testing with chaos scenarios."""

    def __init__(self):
        self.test_portfolio_id = "test_kill_switch_portfolio"
        self._results: list[ChaosTestResult] = []

    def setup_test_portfolio(self, initial_cash: float = 100000.0) -> str:
        """Create a fresh test portfolio."""
        create_portfolio(self.test_portfolio_id, "test_user", initial_cash)
        return self.test_portfolio_id

    def cleanup_test_portfolio(self):
        """Remove test portfolio."""
        from app.services.database import get_connection
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM portfolio_events WHERE portfolio_id = ?", (self.test_portfolio_id,))
            cur.execute("DELETE FROM cash_ledger WHERE portfolio_id = ?", (self.test_portfolio_id,))
            cur.execute("DELETE FROM fills WHERE order_id IN (SELECT id FROM paper_orders WHERE portfolio_id = ?)", (self.test_portfolio_id,))
            cur.execute("DELETE FROM paper_orders WHERE portfolio_id = ?", (self.test_portfolio_id,))
            cur.execute("DELETE FROM positions WHERE portfolio_id = ?", (self.test_portfolio_id,))
            cur.execute("DELETE FROM portfolios WHERE id = ?", (self.test_portfolio_id,))
            conn.commit()

    def get_standard_scenarios(self) -> list[ChaosTestScenario]:
        """Get standard kill switch test scenarios."""
        return [
            ChaosTestScenario(
                name="daily_loss_limit_breach",
                description="Portfolio loses more than daily loss limit, kill switch should activate",
                trigger=KillSwitchTrigger.DAILY_LOSS_LIMIT,
                setup_fn="create_large_unrealized_loss",
                expected_activation_time_seconds=0.1,
            ),
            ChaosTestScenario(
                name="manual_kill_switch",
                description="Manual kill switch activation blocks all new orders",
                trigger=KillSwitchTrigger.MANUAL,
                setup_fn="activate_manual_kill_switch",
                expected_activation_time_seconds=0.01,
            ),
            ChaosTestScenario(
                name="exposure_limit_breach",
                description="Order exceeding gross exposure limit rejected",
                trigger=KillSwitchTrigger.EXPOSURE_LIMIT,
                setup_fn="create_high_exposure_position",
                expected_activation_time_seconds=0.05,
            ),
            ChaosTestScenario(
                name="concentration_limit_breach",
                description="Order exceeding instrument concentration limit rejected",
                trigger=KillSwitchTrigger.CONCENTRATION_LIMIT,
                setup_fn="create_concentrated_position",
                expected_activation_time_seconds=0.05,
            ),
            ChaosTestScenario(
                name="rapid_fire_orders_during_kill",
                description="Multiple orders submitted during active kill switch all rejected",
                trigger=KillSwitchTrigger.CHAOS_TEST,
                setup_fn="activate_kill_switch_then_submit_orders",
                expected_activation_time_seconds=0.01,
            ),
            ChaosTestScenario(
                name="kill_switch_reset_allows_orders",
                description="After reset, new orders are accepted again",
                trigger=KillSwitchTrigger.CHAOS_TEST,
                setup_fn="activate_then_reset_kill_switch",
                expected_activation_time_seconds=0.01,
            ),
        ]

    async def run_scenario(self, scenario: ChaosTestScenario) -> ChaosTestResult:
        """Run a single chaos test scenario."""
        start_time = datetime.now(timezone.utc)
        risk_engine = get_risk_engine()

        try:
            if scenario.setup_fn == "create_large_unrealized_loss":
                await self._setup_large_loss()
                result = risk_engine.check_order(
                    self.test_portfolio_id,
                    self._create_test_order("AAPL", OrderSide.BUY, 1),
                    150.0,
                )
                activation_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                passed = result[0] == "kill_switch"
                status = TestStatus.PASSED if passed else TestStatus.FAILED

            elif scenario.setup_fn == "activate_manual_kill_switch":
                risk_engine.activate_kill_switch("Test manual activation")
                result = risk_engine.check_order(
                    self.test_portfolio_id,
                    self._create_test_order("AAPL", OrderSide.BUY, 1),
                    150.0,
                )
                activation_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                passed = result[0] == "kill_switch"
                status = TestStatus.PASSED if passed else TestStatus.FAILED
                risk_engine.reset_kill_switch()

            elif scenario.setup_fn == "create_high_exposure_position":
                await self._setup_high_exposure()
                result = risk_engine.check_order(
                    self.test_portfolio_id,
                    self._create_test_order("GOOGL", OrderSide.BUY, 1000),
                    2000.0,
                )
                activation_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                passed = result[0] == "rejected"
                status = TestStatus.PASSED if passed else TestStatus.FAILED

            elif scenario.setup_fn == "create_concentrated_position":
                await self._setup_concentrated_position()
                result = risk_engine.check_order(
                    self.test_portfolio_id,
                    self._create_test_order("AAPL", OrderSide.BUY, 100),
                    150.0,
                )
                activation_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                passed = result[0] == "rejected"
                status = TestStatus.PASSED if passed else TestStatus.FAILED

            elif scenario.setup_fn == "activate_kill_switch_then_submit_orders":
                risk_engine.activate_kill_switch("Chaos test")
                all_rejected = True
                for _ in range(10):
                    result = risk_engine.check_order(
                        self.test_portfolio_id,
                        self._create_test_order("AAPL", OrderSide.BUY, 1),
                        150.0,
                    )
                    if result[0] != "kill_switch":
                        all_rejected = False
                        break
                activation_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                passed = all_rejected
                status = TestStatus.PASSED if passed else TestStatus.FAILED
                risk_engine.reset_kill_switch()

            elif scenario.setup_fn == "activate_then_reset_kill_switch":
                risk_engine.activate_kill_switch("Test reset")
                risk_engine.reset_kill_switch()
                result = risk_engine.check_order(
                    self.test_portfolio_id,
                    self._create_test_order("AAPL", OrderSide.BUY, 1),
                    150.0,
                )
                activation_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                passed = result[0] == "passed"
                status = TestStatus.PASSED if passed else TestStatus.FAILED

            else:
                raise ValueError(f"Unknown setup function: {scenario.setup_fn}")

            return ChaosTestResult(
                scenario_name=scenario.name,
                status=status,
                activation_time_ms=activation_time,
                expected_time_ms=scenario.expected_activation_time_seconds * 1000,
                error_message=None if passed else f"Expected kill switch/rejection, got {result[0]}",
                details={
                    "trigger": scenario.trigger.value,
                    "description": scenario.description,
                },
            )

        except Exception as e:
            activation_time = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
            return ChaosTestResult(
                scenario_name=scenario.name,
                status=TestStatus.ERROR,
                activation_time_ms=activation_time,
                expected_time_ms=scenario.expected_activation_time_seconds * 1000,
                error_message=str(e),
                details={
                    "trigger": scenario.trigger.value,
                    "description": scenario.description,
                },
            )

    async def run_all_scenarios(self) -> list[ChaosTestResult]:
        """Run all standard kill switch test scenarios."""
        self.setup_test_portfolio()
        scenarios = self.get_standard_scenarios()
        results = []

        for scenario in scenarios:
            self.cleanup_test_portfolio()
            self.setup_test_portfolio()
            result = await self.run_scenario(scenario)
            results.append(result)

        self.cleanup_test_portfolio()
        self._results = results
        return results

    def _create_test_order(self, instrument: str, side: OrderSide, qty: float):
        from app.models import Order, OrderType
        return Order(
            id=f"test_{uuid4()}",
            instrument=instrument,
            side=side,
            order_type=OrderType.MARKET,
            quantity=qty,
            account_id=self.test_portfolio_id,
        )

    async def _setup_large_loss(self):
        """Create positions with large unrealized loss to trigger daily loss limit."""
        portfolio = get_portfolio(self.test_portfolio_id)
        if not portfolio:
            return

        update_position(
            self.test_portfolio_id,
            "AAPL",
            1000,
            200.0,
            100000.0,
            -15000.0,
            0.0,
        )
        update_portfolio_cash(self.test_portfolio_id, 50000.0, 150000.0, 150000.0)

    async def _setup_high_exposure(self):
        """Create high exposure positions."""
        portfolio = get_portfolio(self.test_portfolio_id)
        if not portfolio:
            return

        update_position(
            self.test_portfolio_id,
            "AAPL",
            200,
            150.0,
            30000.0,
            0.0,
            0.0,
        )
        update_position(
            self.test_portfolio_id,
            "MSFT",
            100,
            300.0,
            30000.0,
            0.0,
            0.0,
        )
        update_portfolio_cash(self.test_portfolio_id, 40000.0, 100000.0, 100000.0)

    async def _setup_concentrated_position(self):
        """Create concentrated position."""
        portfolio = get_portfolio(self.test_portfolio_id)
        if not portfolio:
            return

        update_position(
            self.test_portfolio_id,
            "AAPL",
            500,
            150.0,
            75000.0,
            0.0,
            0.0,
        )
        update_portfolio_cash(self.test_portfolio_id, 25000.0, 100000.0, 100000.0)

    def generate_test_report(self) -> dict:
        """Generate kill switch test report."""
        if not self._results:
            return {"error": "No test results available"}

        total = len(self._results)
        passed = sum(1 for r in self._results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self._results if r.status == TestStatus.FAILED)
        errors = sum(1 for r in self._results if r.status == TestStatus.ERROR)

        avg_activation_time = sum(r.activation_time_ms or 0 for r in self._results) / total if total > 0 else 0
        max_activation_time = max((r.activation_time_ms or 0) for r in self._results) if total > 0 else 0

        return {
            "summary": {
                "total_scenarios": total,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "pass_rate": passed / total if total > 0 else 0,
                "avg_activation_time_ms": round(avg_activation_time, 2),
                "max_activation_time_ms": round(max_activation_time, 2),
            },
            "results": [
                {
                    "scenario": r.scenario_name,
                    "status": r.status.value,
                    "activation_time_ms": r.activation_time_ms,
                    "expected_time_ms": r.expected_time_ms,
                    "within_sla": (r.activation_time_ms or float('inf')) <= r.expected_time_ms,
                    "error": r.error_message,
                }
                for r in self._results
            ],
            "runbook": self._generate_runbook(),
        }

    def _generate_runbook(self) -> dict:
        """Generate operational runbook for kill switch procedures."""
        return {
            "activation_procedures": [
                {
                    "trigger": "daily_loss_limit",
                    "description": "Automatic activation when daily P&L exceeds limit",
                    "steps": [
                        "Risk engine detects daily loss limit breach",
                        "Kill switch activated automatically",
                        "All new orders rejected with 403",
                        "Alert sent to operations team",
                        "Manual review required before reset",
                    ],
                },
                {
                    "trigger": "manual",
                    "description": "Manual activation by risk officer or automated system",
                    "steps": [
                        "Risk officer identifies market anomaly or system issue",
                        "Calls POST /api/v1/risk/kill-switch/activate",
                        "All new orders immediately rejected",
                        "Existing open orders can be cancelled via API",
                        "Document reason in incident log",
                    ],
                },
            ],
            "reset_procedures": [
                {
                    "condition": "Root cause identified and resolved",
                    "steps": [
                        "Verify market conditions normalized",
                        "Confirm positions are within risk limits",
                        "Call POST /api/v1/risk/kill-switch/reset",
                        "Verify orders are accepted again",
                        "Close incident in tracking system",
                    ],
                },
            ],
            "monitoring": {
                "key_metrics": [
                    "Kill switch activation latency (<100ms target)",
                    "Order rejection rate during activation",
                    "Time to manual reset",
                    "False positive rate",
                ],
                "alerts": [
                    "Kill switch activated",
                    "Kill switch active > 5 minutes",
                    "Kill switch reset",
                ],
            },
        }


def run_kill_switch_tests() -> dict:
    """Run kill switch tests synchronously."""
    tester = KillSwitchTester()
    return asyncio.run(tester.run_all_scenarios())