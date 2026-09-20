from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional
from uuid import uuid4

import numpy as np

from app.services.database import get_portfolio, get_portfolio_history


class ReportType(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YTD = "ytd"
    CUSTOM = "custom"


class AttributionMethod(str, Enum):
    BRINSON = "brinson"
    BRINSON_FACHER = "brinson_facher"
    SIMPLE = "simple"


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    period_start: date
    period_end: date
    total_return: float
    annualized_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_duration_days: int
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    total_trades: int
    winning_trades: int
    losing_trades: int


@dataclass(frozen=True, slots=True)
class RiskMetrics:
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    beta: float
    alpha: float
    correlation_to_market: float
    tracking_error: float
    information_ratio: float
    downside_deviation: float
    upside_capture: float
    downside_capture: float


@dataclass(frozen=True, slots=True)
class AttributionResult:
    period_start: date
    period_end: date
    method: AttributionMethod
    total_allocation_effect: float
    total_selection_effect: float
    total_interaction_effect: float
    total_active_return: float
    by_sector: list[dict]
    by_instrument: list[dict]


@dataclass(frozen=True, slots=True)
class PortfolioReport:
    portfolio_id: str
    report_type: ReportType
    period_start: date
    period_end: date
    generated_at: datetime
    performance: PerformanceMetrics
    risk: RiskMetrics
    attribution: Optional[AttributionResult]
    equity_curve: list[dict]
    trades: list[dict]
    positions_snapshot: list[dict]


def _quantize(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _quantize_pct(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def calculate_returns(equity_curve: list[dict]) -> np.ndarray:
    """Calculate daily returns from equity curve."""
    if len(equity_curve) < 2:
        return np.array([])

    equities = np.array([e["equity"] for e in equity_curve])
    returns = np.diff(equities) / equities[:-1]
    return returns


def calculate_performance_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    period_start: date,
    period_end: date,
    risk_free_rate: float = 0.02,
) -> PerformanceMetrics:
    """Calculate comprehensive performance metrics."""
    if not equity_curve:
        return PerformanceMetrics(
            period_start=period_start,
            period_end=period_end,
            total_return=0.0,
            annualized_return=0.0,
            volatility=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            max_drawdown_duration_days=0,
            calmar_ratio=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
        )

    returns = calculate_returns(equity_curve)
    if len(returns) == 0:
        returns = np.array([0.0])

    total_return = (equity_curve[-1]["equity"] - equity_curve[0]["equity"]) / equity_curve[0]["equity"]
    days = (period_end - period_start).days or 1
    annualized_return = (1 + total_return) ** (252 / days) - 1

    volatility = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0.0
    excess_returns = returns - risk_free_rate / 252
    sharpe_ratio = np.mean(excess_returns) / (np.std(excess_returns) + 1e-6) * np.sqrt(252) if len(returns) > 1 else 0.0

    downside_returns = returns[returns < 0]
    downside_deviation = np.std(downside_returns) * np.sqrt(252) if len(downside_returns) > 1 else 0.0
    sortino_ratio = np.mean(excess_returns) / (downside_deviation / np.sqrt(252) + 1e-6) if downside_deviation > 0 else 0.0

    cumulative = np.cumprod(1 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 0.0

    drawdown_duration = 0
    current_duration = 0
    for dd in drawdown:
        if dd < 0:
            current_duration += 1
            drawdown_duration = max(drawdown_duration, current_duration)
        else:
            current_duration = 0

    calmar_ratio = annualized_return / max_drawdown if max_drawdown > 0 else 0.0

    if trades:
        pnls = [t.get("pnl", 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        winning_trades = len(wins)
        losing_trades = len(losses)
        total_trades = len(trades)
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        profit_factor = sum(wins) / abs(sum(losses)) if losses else float('inf')
    else:
        win_rate = 0.0
        profit_factor = 0.0
        avg_win = 0.0
        avg_loss = 0.0
        total_trades = 0
        winning_trades = 0
        losing_trades = 0

    return PerformanceMetrics(
        period_start=period_start,
        period_end=period_end,
        total_return=_quantize_pct(total_return),
        annualized_return=_quantize_pct(annualized_return),
        volatility=_quantize_pct(volatility),
        sharpe_ratio=_quantize(sharpe_ratio),
        sortino_ratio=_quantize(sortino_ratio),
        max_drawdown=_quantize_pct(max_drawdown),
        max_drawdown_duration_days=drawdown_duration,
        calmar_ratio=_quantize(calmar_ratio),
        win_rate=_quantize_pct(win_rate),
        profit_factor=_quantize(profit_factor) if profit_factor != float('inf') else None,
        avg_win=_quantize(avg_win),
        avg_loss=_quantize(avg_loss),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
    )


def calculate_risk_metrics(
    equity_curve: list[dict],
    market_returns: Optional[np.ndarray] = None,
    confidence_levels: list[float] = [0.95, 0.99],
) -> RiskMetrics:
    """Calculate risk metrics including VaR, CVaR, and market-relative metrics."""
    returns = calculate_returns(equity_curve)
    if len(returns) == 0:
        return RiskMetrics(
            var_95=0.0,
            var_99=0.0,
            cvar_95=0.0,
            cvar_99=0.0,
            beta=0.0,
            alpha=0.0,
            correlation_to_market=0.0,
            tracking_error=0.0,
            information_ratio=0.0,
            downside_deviation=0.0,
            upside_capture=0.0,
            downside_capture=0.0,
        )

    var_values = {}
    cvar_values = {}
    for cl in confidence_levels:
        var = np.percentile(returns, (1 - cl) * 100)
        cvar = np.mean(returns[returns <= var])
        var_values[f"var_{int(cl*100)}"] = _quantize_pct(var)
        cvar_values[f"cvar_{int(cl*100)}"] = _quantize_pct(cvar)

    beta = 0.0
    alpha = 0.0
    correlation = 0.0
    tracking_error = 0.0
    information_ratio = 0.0
    upside_capture = 0.0
    downside_capture = 0.0

    if market_returns is not None and len(market_returns) == len(returns):
        covariance = np.cov(returns, market_returns)[0, 1]
        market_variance = np.var(market_returns)
        if market_variance > 0:
            beta = covariance / market_variance
            alpha = np.mean(returns) - beta * np.mean(market_returns)
            correlation = np.corrcoef(returns, market_returns)[0, 1]
            if np.isnan(correlation):
                correlation = 0.0

        active_returns = returns - market_returns
        tracking_error = np.std(active_returns) * np.sqrt(252)
        information_ratio = np.mean(active_returns) / (np.std(active_returns) + 1e-6) * np.sqrt(252) if len(active_returns) > 1 else 0.0

        up_market = market_returns > 0
        down_market = market_returns < 0
        if np.any(up_market):
            upside_capture = np.mean(returns[up_market]) / np.mean(market_returns[up_market])
        if np.any(down_market):
            downside_capture = np.mean(returns[down_market]) / np.mean(market_returns[down_market])

    downside_returns = returns[returns < 0]
    downside_deviation = np.std(downside_returns) * np.sqrt(252) if len(downside_returns) > 1 else 0.0

    return RiskMetrics(
        var_95=var_values.get("var_95", 0.0),
        var_99=var_values.get("var_99", 0.0),
        cvar_95=cvar_values.get("cvar_95", 0.0),
        cvar_99=cvar_values.get("cvar_99", 0.0),
        beta=_quantize(beta),
        alpha=_quantize_pct(alpha),
        correlation_to_market=_quantize_pct(correlation),
        tracking_error=_quantize_pct(tracking_error),
        information_ratio=_quantize(information_ratio),
        downside_deviation=_quantize_pct(downside_deviation),
        upside_capture=_quantize(upside_capture),
        downside_capture=_quantize(downside_capture),
    )


def calculate_brinson_attribution(
    portfolio_weights: dict[str, float],
    benchmark_weights: dict[str, float],
    portfolio_returns: dict[str, float],
    benchmark_returns: dict[str, float],
) -> AttributionResult:
    """Calculate Brinson attribution (allocation + selection + interaction)."""
    all_sectors = set(portfolio_weights.keys()) | set(benchmark_weights.keys())

    allocation_effects = {}
    selection_effects = {}
    interaction_effects = {}

    total_allocation = 0.0
    total_selection = 0.0
    total_interaction = 0.0

    for sector in all_sectors:
        wp = portfolio_weights.get(sector, 0.0)
        wb = benchmark_weights.get(sector, 0.0)
        rp = portfolio_returns.get(sector, 0.0)
        rb = benchmark_returns.get(sector, 0.0)

        allocation = (wp - wb) * rb
        selection = wb * (rp - rb)
        interaction = (wp - wb) * (rp - rb)

        allocation_effects[sector] = _quantize_pct(allocation)
        selection_effects[sector] = _quantize_pct(selection)
        interaction_effects[sector] = _quantize_pct(interaction)

        total_allocation += allocation
        total_selection += selection
        total_interaction += interaction

    by_sector = [
        {
            "sector": sector,
            "portfolio_weight": _quantize_pct(portfolio_weights.get(sector, 0.0)),
            "benchmark_weight": _quantize_pct(benchmark_weights.get(sector, 0.0)),
            "portfolio_return": _quantize_pct(portfolio_returns.get(sector, 0.0)),
            "benchmark_return": _quantize_pct(benchmark_returns.get(sector, 0.0)),
            "allocation_effect": allocation_effects.get(sector, 0.0),
            "selection_effect": selection_effects.get(sector, 0.0),
            "interaction_effect": interaction_effects.get(sector, 0.0),
            "total_effect": _quantize_pct(
                allocation_effects.get(sector, 0.0)
                + selection_effects.get(sector, 0.0)
                + interaction_effects.get(sector, 0.0)
            ),
        }
        for sector in all_sectors
    ]

    total_active = total_allocation + total_selection + total_interaction

    return AttributionResult(
        period_start=date.today(),
        period_end=date.today(),
        method=AttributionMethod.BRINSON,
        total_allocation_effect=_quantize_pct(total_allocation),
        total_selection_effect=_quantize_pct(total_selection),
        total_interaction_effect=_quantize_pct(total_interaction),
        total_active_return=_quantize_pct(total_active),
        by_sector=by_sector,
        by_instrument=[],
    )


class ReportingService:
    """Generate comprehensive portfolio reports."""

    def __init__(self, portfolio_id: str):
        self.portfolio_id = portfolio_id

    def get_equity_curve(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """Get equity curve from cash ledger history."""
        history = get_portfolio_history(self.portfolio_id, limit=10000)
        equity_curve = []

        cash_flows = {}
        for entry in history:
            ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).date()
            if start_date <= ts <= end_date:
                if ts not in cash_flows:
                    cash_flows[ts] = 0.0
                cash_flows[ts] += entry["amount"]

        portfolio = get_portfolio(self.portfolio_id)
        current_equity = portfolio.get("equity", 0) if portfolio else 0

        dates = sorted(cash_flows.keys())
        for d in dates:
            current_equity += cash_flows[d]
            equity_curve.append({
                "date": d.isoformat(),
                "equity": current_equity,
                "cash_flow": cash_flows[d],
            })

        return equity_curve

    def get_trades(
        self,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        """Get trades for the period."""
        portfolio = get_portfolio(self.portfolio_id)
        if not portfolio:
            return []

        trades = []
        for fill in portfolio.get("recent_fills", []):
            fill_time = datetime.fromisoformat(fill["timestamp"].replace("Z", "+00:00")).date()
            if start_date <= fill_time <= end_date:
                pnl = 0.0
                trades.append({
                    **fill,
                    "pnl": pnl,
                })
        return trades

    def generate_report(
        self,
        report_type: ReportType,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        benchmark_returns: Optional[dict] = None,
    ) -> PortfolioReport:
        """Generate a comprehensive portfolio report."""
        end = end_date or date.today()
        start = start_date or (end - timedelta(days=30))

        if report_type == ReportType.YTD:
            start = date(end.year, 1, 1)

        equity_curve = self.get_equity_curve(start, end)
        trades = self.get_trades(start, end)

        market_returns = None
        if benchmark_returns:
            market_returns = np.array(list(benchmark_returns.values()))

        performance = calculate_performance_metrics(equity_curve, trades, start, end)
        risk = calculate_risk_metrics(equity_curve, market_returns)

        attribution = None
        if benchmark_returns:
            portfolio_weights = {t["instrument_id"]: t.get("market_value", 0) for t in get_portfolio(self.portfolio_id).get("positions", [])}
            total_mv = sum(portfolio_weights.values())
            if total_mv > 0:
                portfolio_weights = {k: v / total_mv for k, v in portfolio_weights.items()}

            bench_weights = {k: v for k, v in benchmark_returns.items() if k in portfolio_weights}
            port_returns = {k: 0.0 for k in portfolio_weights}

            attribution = calculate_brinson_attribution(
                portfolio_weights,
                bench_weights,
                port_returns,
                bench_weights,
            )

        portfolio = get_portfolio(self.portfolio_id)
        positions_snapshot = portfolio.get("positions", []) if portfolio else []

        return PortfolioReport(
            portfolio_id=self.portfolio_id,
            report_type=report_type,
            period_start=start,
            period_end=end,
            generated_at=datetime.now(timezone.utc),
            performance=performance,
            risk=risk,
            attribution=attribution,
            equity_curve=equity_curve,
            trades=trades,
            positions_snapshot=positions_snapshot,
        )

    def generate_report_dict(self, report: PortfolioReport) -> dict:
        """Convert report to dictionary for serialization."""
        result = {
            "portfolio_id": report.portfolio_id,
            "report_type": report.report_type.value,
            "period_start": report.period_start.isoformat(),
            "period_end": report.period_end.isoformat(),
            "generated_at": report.generated_at.isoformat(),
            "performance": {
                "total_return": report.performance.total_return,
                "annualized_return": report.performance.annualized_return,
                "volatility": report.performance.volatility,
                "sharpe_ratio": report.performance.sharpe_ratio,
                "sortino_ratio": report.performance.sortino_ratio,
                "max_drawdown": report.performance.max_drawdown,
                "max_drawdown_duration_days": report.performance.max_drawdown_duration_days,
                "calmar_ratio": report.performance.calmar_ratio,
                "win_rate": report.performance.win_rate,
                "profit_factor": report.performance.profit_factor,
                "avg_win": report.performance.avg_win,
                "avg_loss": report.performance.avg_loss,
                "total_trades": report.performance.total_trades,
                "winning_trades": report.performance.winning_trades,
                "losing_trades": report.performance.losing_trades,
            },
            "risk": {
                "var_95": report.risk.var_95,
                "var_99": report.risk.var_99,
                "cvar_95": report.risk.cvar_95,
                "cvar_99": report.risk.cvar_99,
                "beta": report.risk.beta,
                "alpha": report.risk.alpha,
                "correlation_to_market": report.risk.correlation_to_market,
                "tracking_error": report.risk.tracking_error,
                "information_ratio": report.risk.information_ratio,
                "downside_deviation": report.risk.downside_deviation,
                "upside_capture": report.risk.upside_capture,
                "downside_capture": report.risk.downside_capture,
            },
            "equity_curve": report.equity_curve,
            "trades": report.trades,
            "positions_snapshot": report.positions_snapshot,
        }

        if report.attribution:
            result["attribution"] = {
                "method": report.attribution.method.value,
                "total_allocation_effect": report.attribution.total_allocation_effect,
                "total_selection_effect": report.attribution.total_selection_effect,
                "total_interaction_effect": report.attribution.total_interaction_effect,
                "total_active_return": report.attribution.total_active_return,
                "by_sector": report.attribution.by_sector,
                "by_instrument": report.attribution.by_instrument,
            }

        return result