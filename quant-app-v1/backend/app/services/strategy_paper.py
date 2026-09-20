from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from uuid import uuid4

from app.services.database import get_portfolio, get_portfolio_history
from app.models import Strategy, StrategyVersion, StrategyStatus


@dataclass(frozen=True, slots=True)
class PaperTrade:
    order_id: str
    fill_id: str
    instrument: str
    side: str
    qty: float
    price: float
    commission: float
    timestamp: datetime
    strategy_version_id: Optional[str]


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    trade_id: str
    instrument: str
    side: str
    entry_price: float
    exit_price: float
    qty: float
    entry_time: datetime
    exit_time: datetime
    pnl_pct: float
    strategy_version_id: int


@dataclass(frozen=True, slots=True)
class ComparisonMetrics:
    strategy_version_id: str
    period_start: date
    period_end: date
    paper_trades: int
    backtest_trades: int
    paper_total_pnl: float
    backtest_total_pnl: float
    paper_win_rate: float
    backtest_win_rate: float
    paper_sharpe: float
    backtest_sharpe: float
    paper_max_drawdown: float
    backtest_max_drawdown: float
    correlation: float
    tracking_error: float


@dataclass(frozen=True, slots=True)
class StrategyPaperLink:
    strategy_id: str
    strategy_version_id: str
    portfolio_id: str
    activated_at: datetime
    deactivated_at: Optional[datetime]
    status: str
    config: dict = field(default_factory=dict)


def _quantize(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class StrategyPaperService:
    """Link StrategyVersions to paper trading portfolios and track performance."""

    def __init__(self, portfolio_id: str):
        self.portfolio_id = portfolio_id
        self._active_links: dict[str, StrategyPaperLink] = {}

    def activate_strategy(
        self,
        strategy_id: str,
        strategy_version_id: str,
        config: Optional[dict] = None,
    ) -> StrategyPaperLink:
        """Activate a strategy version for paper trading."""
        link = StrategyPaperLink(
            strategy_id=strategy_id,
            strategy_version_id=strategy_version_id,
            portfolio_id=self.portfolio_id,
            activated_at=datetime.now(timezone.utc),
            deactivated_at=None,
            status="active",
            config=config or {},
        )
        self._active_links[strategy_version_id] = link
        return link

    def deactivate_strategy(self, strategy_version_id: str) -> Optional[StrategyPaperLink]:
        """Deactivate a strategy version."""
        link = self._active_links.get(strategy_version_id)
        if link:
            link = StrategyPaperLink(
                strategy_id=link.strategy_id,
                strategy_version_id=link.strategy_version_id,
                portfolio_id=link.portfolio_id,
                activated_at=link.activated_at,
                deactivated_at=datetime.now(timezone.utc),
                status="inactive",
                config=link.config,
            )
            self._active_links[strategy_version_id] = link
        return link

    def get_active_strategies(self) -> list[StrategyPaperLink]:
        return [l for l in self._active_links.values() if l.status == "active"]

    def get_strategy_link(self, strategy_version_id: str) -> Optional[StrategyPaperLink]:
        return self._active_links.get(strategy_version_id)

    def record_paper_trade(
        self,
        order_id: str,
        fill_id: str,
        instrument: str,
        side: str,
        qty: float,
        price: float,
        commission: float,
        strategy_version_id: Optional[str],
    ) -> PaperTrade:
        """Record a paper trade linked to a strategy version."""
        return PaperTrade(
            order_id=order_id,
            fill_id=fill_id,
            instrument=instrument,
            side=side,
            qty=qty,
            price=price,
            commission=commission,
            timestamp=datetime.now(timezone.utc),
            strategy_version_id=strategy_version_id,
        )


class PaperVsBacktestComparator:
    """Compare paper trading performance against backtest results."""

    def __init__(self, portfolio_id: str):
        self.portfolio_id = portfolio_id

    def get_paper_trades(
        self,
        strategy_version_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[PaperTrade]:
        """Get paper trades from portfolio, optionally filtered by strategy version."""
        portfolio = get_portfolio(self.portfolio_id)
        if not portfolio:
            return []

        trades = []
        for fill in portfolio.get("recent_fills", []):
            if fill.get("strategy_version_id") and strategy_version_id:
                if fill["strategy_version_id"] != strategy_version_id:
                    continue

            fill_time = datetime.fromisoformat(fill["timestamp"].replace("Z", "+00:00"))
            if start_date and fill_time.date() < start_date:
                continue
            if end_date and fill_time.date() > end_date:
                continue

            trades.append(PaperTrade(
                order_id=fill.get("order_id", ""),
                fill_id=fill["id"],
                instrument=fill["instrument_id"],
                side=fill["side"],
                qty=fill["qty"],
                price=fill["price"],
                commission=fill.get("commission", 0),
                timestamp=fill_time,
                strategy_version_id=fill.get("strategy_version_id"),
            ))

        return trades

    def get_backtest_trades(
        self,
        strategy_version_id: int,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> list[BacktestTrade]:
        """Get backtest trades from database."""
        from app.services.database import get_connection

        with get_connection() as conn:
            conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
            cur = conn.cursor()
            cur.execute(
                """SELECT * FROM trades WHERE backtest_id IN (
                    SELECT id FROM backtests WHERE strategy_version = ?
                )""",
                (strategy_version_id,),
            )
            rows = cur.fetchall()

        trades = []
        for row in rows:
            entry_time = datetime.fromisoformat(row["signal_time"].replace("Z", "+00:00"))
            exit_time = entry_time + timedelta(days=1)

            if start_date and entry_time.date() < start_date:
                continue
            if end_date and entry_time.date() > end_date:
                continue

            trades.append(BacktestTrade(
                trade_id=str(row["id"]),
                instrument=row["symbol"],
                side=row["direction"].lower(),
                entry_price=row["entry_price"],
                exit_price=row["exit_price"],
                qty=1.0,
                entry_time=entry_time,
                exit_time=exit_time,
                pnl_pct=row["pnl_pct"],
                strategy_version_id=strategy_version_id,
            ))

        return trades

    def calculate_metrics(self, trades: list[PaperTrade] | list[BacktestTrade]) -> dict:
        """Calculate performance metrics from trades."""
        if not trades:
            return {
                "total_trades": 0,
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
            }

        pnls = []
        wins = 0
        losses = 0
        total_win = 0.0
        total_loss = 0.0

        for trade in trades:
            if isinstance(trade, PaperTrade):
                pnl = (trade.price * trade.qty) - (trade.price * trade.qty)
            else:
                pnl = trade.pnl_pct

            pnls.append(pnl)
            if pnl > 0:
                wins += 1
                total_win += pnl
            else:
                losses += 1
                total_loss += abs(pnl)

        total_pnl = sum(pnls)
        win_rate = wins / len(trades) if trades else 0
        avg_win = total_win / wins if wins else 0
        avg_loss = total_loss / losses if losses else 0
        profit_factor = total_win / total_loss if total_loss else float('inf')

        import numpy as np
        returns = np.array(pnls)
        sharpe = np.mean(returns) / (np.std(returns) + 1e-6) * (252 ** 0.5) if len(returns) > 1 else 0

        cumulative = np.cumsum(returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max
        max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 0

        return {
            "total_trades": len(trades),
            "total_pnl": _quantize(total_pnl),
            "win_rate": _quantize(win_rate),
            "avg_win": _quantize(avg_win),
            "avg_loss": _quantize(avg_loss),
            "profit_factor": _quantize(profit_factor) if profit_factor != float('inf') else None,
            "sharpe": _quantize(sharpe),
            "max_drawdown": _quantize(max_drawdown),
        }

    def compare(
        self,
        strategy_version_id: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> ComparisonMetrics:
        """Compare paper vs backtest performance for a strategy version."""
        paper_trades = self.get_paper_trades(strategy_version_id, start_date, end_date)
        backtest_trades = self.get_backtest_trades(int(strategy_version_id), start_date, end_date)

        paper_metrics = self.calculate_metrics(paper_trades)
        backtest_metrics = self.calculate_metrics(backtest_trades)

        paper_pnls = [t.price * t.qty * (1 if t.side == "buy" else -1) for t in paper_trades]
        backtest_pnls = [t.pnl_pct for t in backtest_trades]

        correlation = 0.0
        if paper_pnls and backtest_pnls and len(paper_pnls) == len(backtest_pnls):
            import numpy as np
            correlation = float(np.corrcoef(paper_pnls, backtest_pnls)[0, 1])
            if np.isnan(correlation):
                correlation = 0.0

        tracking_error = 0.0
        if paper_pnls and backtest_pnls:
            import numpy as np
            diff = np.array(paper_pnls) - np.array(backtest_pnls[:len(paper_pnls)])
            tracking_error = float(np.std(diff))

        return ComparisonMetrics(
            strategy_version_id=strategy_version_id,
            period_start=start_date or date.today(),
            period_end=end_date or date.today(),
            paper_trades=len(paper_trades),
            backtest_trades=len(backtest_trades),
            paper_total_pnl=paper_metrics["total_pnl"],
            backtest_total_pnl=backtest_metrics["total_pnl"],
            paper_win_rate=paper_metrics["win_rate"],
            backtest_win_rate=backtest_metrics["win_rate"],
            paper_sharpe=paper_metrics["sharpe"],
            backtest_sharpe=backtest_metrics["sharpe"],
            paper_max_drawdown=paper_metrics["max_drawdown"],
            backtest_max_drawdown=backtest_metrics["max_drawdown"],
            correlation=_quantize(correlation),
            tracking_error=_quantize(tracking_error),
        )

    def generate_comparison_report(self, metrics: ComparisonMetrics) -> dict:
        """Generate detailed comparison report."""
        return {
            "strategy_version_id": metrics.strategy_version_id,
            "period": {
                "start": metrics.period_start.isoformat(),
                "end": metrics.period_end.isoformat(),
            },
            "trade_counts": {
                "paper": metrics.paper_trades,
                "backtest": metrics.backtest_trades,
            },
            "pnl": {
                "paper": metrics.paper_total_pnl,
                "backtest": metrics.backtest_total_pnl,
                "difference": _quantize(metrics.paper_total_pnl - metrics.backtest_total_pnl),
            },
            "win_rate": {
                "paper": metrics.paper_win_rate,
                "backtest": metrics.backtest_win_rate,
                "difference": _quantize(metrics.paper_win_rate - metrics.backtest_win_rate),
            },
            "sharpe": {
                "paper": metrics.paper_sharpe,
                "backtest": metrics.backtest_sharpe,
                "difference": _quantize(metrics.paper_sharpe - metrics.backtest_sharpe),
            },
            "max_drawdown": {
                "paper": metrics.paper_max_drawdown,
                "backtest": metrics.backtest_max_drawdown,
                "difference": _quantize(metrics.paper_max_drawdown - metrics.backtest_max_drawdown),
            },
            "correlation": metrics.correlation,
            "tracking_error": metrics.tracking_error,
            "assessment": self._assess_divergence(metrics),
        }

    def _assess_divergence(self, metrics: ComparisonMetrics) -> str:
        """Assess if paper trading is diverging from backtest."""
        pnl_diff = abs(metrics.paper_total_pnl - metrics.backtest_total_pnl)
        wr_diff = abs(metrics.paper_win_rate - metrics.backtest_win_rate)

        if pnl_diff > 0.2 and wr_diff > 0.2:
            return "SIGNIFICANT_DIVERGENCE"
        elif pnl_diff > 0.1 or wr_diff > 0.15:
            return "MODERATE_DIVERGENCE"
        elif pnl_diff > 0.05 or wr_diff > 0.1:
            return "MINOR_DIVERGENCE"
        return "WITHIN_EXPECTATIONS"