from __future__ import annotations

import asyncio
import json
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.models import (
    Assumptions,
    BacktestRun,
    BacktestRunStatus,
    Candle,
    OrderSide,
    OrderType,
    StrategySpec,
    Timeframe,
)
from app.quant.impact_model import calculate_final_signal
from app.quant.risk_manager import RiskManager, RiskConfig
from app.quant.recognition import find_pivots, detect_head_and_shoulders
from app.quant.technicals import calculate_all_indicators


# --- Enums & Config ---

class ExecutionMode(Enum):
    SIMULATION = "simulation"  # Instant fill at signal price
    REALISTIC = "realistic"    # With spread, slippage, latency, commission


class DataSplit(Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""
    strategy_spec: StrategySpec
    start_date: datetime
    end_date: datetime
    timeframe: Timeframe
    universe: List[str]
    initial_capital: float = 100_000.0
    execution_mode: ExecutionMode = ExecutionMode.REALISTIC
    assumptions: Assumptions = field(default_factory=Assumptions)
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    data_split: DataSplit = DataSplit.TEST
    train_ratio: float = 0.6
    val_ratio: float = 0.2
    test_ratio: float = 0.2
    walk_forward_windows: int = 0  # 0 = single run, >0 = walk-forward
    monte_carlo_runs: int = 0  # 0 = disabled
    seed: int = 42


@dataclass
class Position:
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    entry_time: datetime
    stop_loss: float
    take_profit: float
    commission_paid: float = 0.0


@dataclass
class TradeResult:
    trade_id: str
    symbol: str
    side: OrderSide
    entry_price: float
    exit_price: float
    quantity: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_pct: float
    commission: float
    slippage: float
    exit_reason: str  # "tp", "sl", "signal", "time", "end"
    hold_duration: timedelta


@dataclass
class BacktestReport:
    run_id: str
    config: BacktestConfig
    trades: List[TradeResult]
    equity_curve: List[Tuple[datetime, float]]
    metrics: Dict[str, Any]
    train_metrics: Optional[Dict[str, Any]] = None
    val_metrics: Optional[Dict[str, Any]] = None
    test_metrics: Optional[Dict[str, Any]] = None
    walk_forward_results: Optional[List[Dict[str, Any]]] = None
    monte_carlo_results: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DataSplitter:
    """Handles train/validation/test splits for time-series data."""

    @staticmethod
    def split(
        df: pd.DataFrame,
        train_ratio: float = 0.6,
        val_ratio: float = 0.2,
        test_ratio: float = 0.2,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Split time-series data chronologically."""
        total = len(df)
        train_end = int(total * train_ratio)
        val_end = train_end + int(total * val_ratio)
        
        train = df.iloc[:train_end].copy()
        val = df.iloc[train_end:val_end].copy()
        test = df.iloc[val_end:].copy()
        
        return train, val, test

    @staticmethod
    def walk_forward_windows(
        df: pd.DataFrame,
        n_windows: int,
        train_window: int,
        test_window: int,
        step: int,
    ) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """Generate walk-forward train/test windows."""
        windows = []
        for i in range(n_windows):
            train_start = i * step
            train_end = train_start + train_window
            test_end = min(train_end + test_window, len(df))
            
            if train_end >= len(df) or test_end > len(df):
                break
                
            train_df = df.iloc[train_start:train_end].copy()
            test_df = df.iloc[train_end:test_end].copy()
            windows.append((train_df, test_df))
        
        return windows


class SlippageModel:
    """Models market impact and slippage."""

    def __init__(self, assumptions: Assumptions):
        self.spread_bps = assumptions.spread_bps
        self.slippage_bps = assumptions.slippage_bps
        self.latency_ms = assumptions.latency_ms

    def calculate_fill_price(
        self,
        signal_price: float,
        side: OrderSide,
        volatility: float,
        volume: float,
    ) -> Tuple[float, float]:
        """
        Calculate realistic fill price with spread and slippage.
        Returns (fill_price, slippage_cost).
        """
        # Half-spread cost (always pay half spread on each side)
        half_spread = signal_price * (self.spread_bps / 10000) / 2
        
        # Slippage proportional to volatility and order size
        # Simplified model: slippage increases with volatility and order size
        slippage = signal_price * (self.slippage_bps / 10000) * (1 + volatility * 10)
        
        if side == OrderSide.BUY:
            fill_price = signal_price + half_spread + slippage
        else:
            fill_price = signal_price - half_spread - slippage
        
        total_slippage = half_spread + slippage
        return fill_price, total_slippage


class CommissionModel:
    """Calculates trading commissions."""

    def __init__(self, assumptions: Assumptions):
        self.per_share = assumptions.commission_per_share
        self.min_commission = assumptions.commission_min

    def calculate(self, price: float, quantity: float) -> float:
        commission = max(self.per_share * quantity, self.min_commission)
        return commission


class LatencySimulator:
    """Simulates order latency and price movement during latency."""

    def __init__(self, latency_ms: int):
        self.latency_ms = latency_ms

    def simulate(
        self,
        signal_price: float,
        side: OrderSide,
        next_price: float,
    ) -> float:
        """
        Simulate price movement during order latency.
        Uses next candle price as proxy for price after latency.
        """
        # Simple model: price moves toward next price during latency
        price_change = next_price - signal_price
        
        if side == OrderSide.BUY:
            # Adverse movement hurts buys
            executed_price = signal_price + abs(price_change) * 0.5
        else:
            # Adverse movement hurts sells
            executed_price = signal_price - abs(price_change) * 0.5
        
        return executed_price


class SessionManager:
    """Manages trading sessions and time-based rules."""

    def __init__(self, timezone: str = "America/New_York"):
        self.timezone = timezone

    def is_market_open(self, timestamp: datetime, session_rules: List[Dict]) -> bool:
        """Check if market is open based on session rules."""
        # Simplified: assume RTH (9:30-16:00 ET)
        t = timestamp.astimezone()
        hour = t.hour
        minute = t.minute
        
        # 9:30 = 9.5, 16:00 = 16
        market_open = 9.5
        market_close = 16.0
        current = hour + minute / 60
        
        return market_open <= current < market_close

    def is_in_blocked_window(self, timestamp: datetime, blocked_windows: List[Dict]) -> bool:
        """Check if timestamp falls in a blocked window."""
        for window in blocked_windows:
            start = window.get("start", "00:00")
            end = window.get("end", "00:00")
            start_h, start_m = map(int, start.split(":"))
            end_h, end_m = map(int, end.split(":"))
            
            current_min = timestamp.hour * 60 + timestamp.minute
            start_min = start_h * 60 + start_m
            end_min = end_h * 60 + end_m
            
            if start_min <= current_min < end_min:
                return True
        return False


class BacktestEngine:
    """
    Advanced backtesting engine with realistic execution modeling.
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.risk_manager = RiskManager(total_capital=config.initial_capital, config=config.risk_config)
        self.slippage_model = SlippageModel(config.assumptions)
        self.commission_model = CommissionModel(config.assumptions)
        self.latency_sim = LatencySimulator(config.assumptions.latency_ms)
        self.session_manager = SessionManager()
        
        self.trades: List[TradeResult] = []
        self.open_positions: Dict[str, Position] = {}
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.current_capital = config.initial_capital
        self.peak_capital = config.initial_capital
        self.max_drawdown = 0.0

    async def run(
        self,
        data: Dict[str, pd.DataFrame],
    ) -> BacktestReport:
        """
        Run backtest on provided data.
        
        Args:
            data: Dict mapping symbol -> DataFrame with OHLCV + indicators
        """
        run_id = str(uuid.uuid4())
        self.trades = []
        self.open_positions = {}
        self.equity_curve = [(self.config.start_date, self.current_capital)]
        self.current_capital = self.config.initial_capital
        self.peak_capital = self.config.initial_capital
        self.max_drawdown = 0.0

        # Prepare data
        aligned_data = self._align_data(data)
        if aligned_data.empty:
            raise ValueError("No valid data for backtest")

        # Run based on execution mode
        if self.config.execution_mode == ExecutionMode.SIMULATION:
            await self._run_simulation(aligned_data)
        else:
            await self._run_realistic(aligned_data)

        # Close any remaining positions
        await self._close_all_positions(aligned_data)

        # Generate report
        report = self._generate_report(run_id)
        return report

    def _align_data(self, data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Align multi-symbol data on common timestamp index."""
        # Get common date range
        all_dates = None
        for df in data.values():
            if "time" in df.columns:
                dates = pd.to_datetime(df["time"], unit="s", utc=True)
            elif "timestamp" in df.columns:
                dates = pd.to_datetime(df["timestamp"], utc=True)
            else:
                dates = df.index
            
            if all_dates is None:
                all_dates = dates
            else:
                all_dates = all_dates.intersection(dates)
        
        # Filter each dataframe to common dates
        aligned = {}
        for symbol, df in data.items():
            if "time" in df.columns:
                df = df.set_index(pd.to_datetime(df["time"], unit="s", utc=True))
            elif "timestamp" in df.columns:
                df = df.set_index(pd.to_datetime(df["timestamp"], utc=True))
            
            aligned[symbol] = df.loc[df.index.isin(all_dates)].sort_index()
        
        # Create combined DataFrame with symbol prefix
        combined = pd.DataFrame(index=all_dates)
        for symbol, df in aligned.items():
            for col in ["open", "high", "low", "close", "volume", "RSI", "BB_upper", "BB_lower"]:
                if col in df.columns:
                    combined[f"{symbol}_{col}"] = df[col]
        
        return combined.sort_index()

    async def _run_simulation(self, data: pd.DataFrame):
        """Simple simulation mode (instant fills)."""
        for i in range(len(data)):
            row = data.iloc[i]
            timestamp = data.index[i]
            
            # Check exits first
            await self._check_exits(row, timestamp)
            
            # Generate signals
            await self._generate_signals(row, timestamp)

        # Record equity
        self._record_equity(data.index[-1])

    async def _run_realistic(self, data: pd.DataFrame):
        """Realistic execution with costs, latency, slippage."""
        for i in range(1, len(data)):  # Start at 1 to have next candle for latency
            row = data.iloc[i]
            prev_row = data.iloc[i - 1]
            timestamp = data.index[i]
            prev_timestamp = data.index[i - 1]
            
            # Check exits first (using current prices)
            await self._check_exits_realistic(row, timestamp)
            
            # Generate signals (using previous close to avoid lookahead)
            await self._generate_signals_realistic(prev_row, prev_timestamp, row, timestamp)
            
            # Record equity
            self._record_equity(timestamp)

    async def _check_exits(self, row: pd.Series, timestamp: datetime):
        """Simple exit checking."""
        to_close = []
        for pos_id, pos in self.open_positions.items():
            symbol = pos.symbol
            price_key = f"{symbol}_close"
            if price_key not in row:
                continue
            price = row[price_key]
            
            exit_price = None
            reason = None
            
            if pos.side == OrderSide.BUY:
                if price <= pos.stop_loss:
                    exit_price, reason = pos.stop_loss, "sl"
                elif price >= pos.take_profit:
                    exit_price, reason = pos.take_profit, "tp"
            else:
                if price >= pos.stop_loss:
                    exit_price, reason = pos.stop_loss, "sl"
                elif price <= pos.take_profit:
                    exit_price, reason = pos.take_profit, "tp"
            
            if exit_price:
                to_close.append((pos_id, exit_price, reason, timestamp))
        
        for pos_id, exit_price, reason, ts in to_close:
            await self._close_position(pos_id, exit_price, reason, ts)

    async def _check_exits_realistic(self, row: pd.Series, timestamp: datetime):
        """Exit checking with realistic prices."""
        to_close = []
        for pos_id, pos in self.open_positions.items():
            symbol = pos.symbol
            price_key = f"{symbol}_close"
            high_key = f"{symbol}_high"
            low_key = f"{symbol}_low"
            
            if price_key not in row:
                continue
            
            close_price = row[price_key]
            high_price = row.get(high_key, row[price_key])
            low_price = row.get(low_key, row[price_key])
            
            exit_price = None
            reason = None
            
            if pos.side == OrderSide.BUY:
                # Check stop loss (use low)
                if low_price <= pos.stop_loss:
                    exit_price, reason = pos.stop_loss, "sl"
                # Check take profit (use high)
                elif high_price >= pos.take_profit:
                    exit_price, reason = pos.take_profit, "tp"
            else:
                # Short position
                if high_price >= pos.stop_loss:
                    exit_price, reason = pos.stop_loss, "sl"
                elif low_price <= pos.take_profit:
                    exit_price, reason = pos.take_profit, "tp"
            
            if exit_price:
                to_close.append((pos_id, exit_price, reason, timestamp))
        
        for pos_id, exit_price, reason, ts in to_close:
            await self._close_position_realistic(pos_id, exit_price, reason, ts)

    async def _generate_signals(self, row: pd.Series, timestamp: datetime):
        """Simple signal generation."""
        for symbol in self.config.universe:
            symbol_key = f"{symbol}_close"
            if symbol_key not in row:
                continue
            
            price = row[symbol_key]
            rsi_key = f"{symbol}_RSI"
            rsi = row.get(rsi_key, 50)
            
            # Simple RSI mean reversion
            if rsi < 30:
                direction, confidence = "Bullish", 0.7
            elif rsi > 70:
                direction, confidence = "Bearish", 0.7
            else:
                continue
            
            # Risk sizing
            vol = self._estimate_volatility(symbol)
            capital = self.risk_manager.calculate_position_size(price, vol)
            if capital <= 0:
                continue
            
            quantity = capital / price
            if quantity <= 0:
                continue
            
            # Check exposure
            exposure = sum(p.quantity * p.entry_price for p in self.open_positions.values())
            if not self.risk_manager.validate_exposure(exposure, capital):
                continue
            
            # Open position
            pos_id = str(uuid.uuid4())
            exits = self.risk_manager.get_exit_levels(row[f"{symbol}_close"], "Long" if direction == "Bullish" else "Short")
            
            self.open_positions[pos_id] = Position(
                symbol=symbol,
                side=OrderSide.BUY if direction == "Bullish" else OrderSide.SELL,
                quantity=capital / price,
                entry_price=price,
                entry_time=timestamp,
                stop_loss=exits["stop_loss"],
                take_profit=exits["take_profit"],
            )

    async def _generate_signals_realistic(
        self,
        prev_row: pd.Series,
        prev_timestamp: datetime,
        curr_row: pd.Series,
        curr_timestamp: datetime,
    ):
        """Signal generation with session and event filters."""
        # Check session rules
        if not self._is_session_allowed(prev_timestamp):
            return
        
        # Check event blackout
        if self._is_event_blackout(prev_timestamp):
            return
        
        for symbol in self.config.universe:
            price_key = f"{symbol}_close"
            rsi_key = f"{symbol}_RSI"
            
            if price_key not in prev_row or rsi_key not in prev_row:
                continue
            
            price = prev_row[price_key]
            rsi = prev_row[rsi_key]
            
            # Pattern detection (using previous candles to avoid lookahead)
            # In real implementation, would use pattern detection on historical window
            
            # Simple RSI signal
            if rsi < 30:
                direction, confidence = "Bullish", 0.7
            elif rsi > 70:
                direction, confidence = "Bearish", 0.7
            else:
                continue
            
            # Risk sizing
            vol = self._estimate_volatility(symbol)
            capital = self.risk_manager.calculate_position_size(price, vol)
            if capital <= 0:
                continue
            
            # Check exposure
            exposure = sum(p.quantity * p.entry_price for p in self.open_positions.values())
            if not self.risk_manager.validate_exposure(exposure, capital):
                continue
            
            # Simulate order latency - use current close as fill reference
            signal_price = prev_row[f"{symbol}_close"]
            curr_price = self.config.universe and curr_row.get(f"{self.config.universe[0]}_close", signal_price)
            
            # Simulate latency
            fill_price = self.latency_sim.simulate(signal_price, 
                OrderSide.BUY if "Bullish" == "Bullish" else OrderSide.SELL, curr_price)
            
            # Apply slippage and spread
            vol = self._estimate_volatility(symbol)
            fill_price, slippage = self.slippage_model.calculate_fill_price(
                fill_price,
                OrderSide.BUY if direction == "Bullish" else OrderSide.SELL,
                self._estimate_volatility(symbol),
                1000000,  # dummy volume
            )
            
            commission = self.commission_model.calculate(fill_price, capital / fill_price)
            
            quantity = capital / fill_price
            if quantity <= 0:
                continue
            
            # Check exposure with fill price
            exposure = sum(p.quantity * p.entry_price for p in self.open_positions.values())
            new_exposure = quantity * fill_price
            if not self.risk_manager.validate_exposure(exposure, new_exposure):
                continue
            
            # Create position
            pos_id = str(uuid.uuid4())
            exits = self.risk_manager.get_exit_levels(fill_price, "Long" if direction == "Bullish" else "Short")
            
            self.open_positions[pos_id] = Position(
                symbol=symbol,
                side=OrderSide.BUY if direction == "Bullish" else OrderSide.SELL,
                quantity=quantity,
                entry_price=fill_price,
                entry_time=prev_timestamp,
                stop_loss=exits["stop_loss"],
                take_profit=exits["take_profit"],
                commission_paid=commission,
            )

    def _estimate_volatility(self, symbol: str) -> float:
        """Estimate recent volatility for position sizing."""
        # Simplified: return fixed volatility
        return 0.02

    def _is_session_allowed(self, timestamp: datetime) -> bool:
        """Check if trading is allowed in current session."""
        for rule in self.config.strategy_spec.session_rules:
            if not rule.enabled:
                continue
            if rule.blocked_windows and self.session_manager.is_in_blocked_window(timestamp, rule.blocked_windows):
                return False
        return True

    def _is_event_blackout(self, timestamp: datetime) -> bool:
        """Check if in event blackout window."""
        # Would check economic calendar in real implementation
        return False

    async def _close_position(self, pos_id: str, exit_price: float, reason: str, timestamp: datetime):
        """Close position in simple mode."""
        pos = self.open_positions.pop(pos_id)
        pnl = (exit_price - pos.entry_price) * pos.quantity if pos.side == OrderSide.BUY else (pos.entry_price - exit_price) * pos.quantity
        pnl_pct = pnl / (pos.entry_price * pos.quantity)
        
        self.current_capital += pnl
        self._update_drawdown()
        
        self.trades.append(TradeResult(
            trade_id=str(uuid.uuid4()),
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            pnl=pnl,
            pnl_pct=pnl_pct,
            commission=0,
            slippage=0,
            exit_reason=reason,
            hold_duration=timestamp - pos.entry_time,
        ))

    async def _close_position_realistic(self, pos_id: str, exit_price: float, reason: str, timestamp: datetime):
        """Close position with realistic costs."""
        pos = self.open_positions.pop(pos_id)
        
        # Calculate exit slippage and commission
        exit_slippage = 0
        exit_commission = 0
        if self.config.execution_mode == ExecutionMode.REALISTIC:
            _, exit_slippage = self.slippage_model.calculate_fill_price(
                pos.entry_price, pos.side, 0.02, 1000000
            )
            exit_commission = self.commission_model.calculate(exit_price, pos.quantity)
        
        # PnL calculation
        if pos.side == OrderSide.BUY:
            gross_pnl = (exit_price - pos.entry_price) * pos.quantity
        else:
            gross_pnl = (pos.entry_price - exit_price) * pos.quantity
        
        total_costs = pos.commission_paid + exit_commission + exit_slippage
        net_pnl = gross_pnl - total_costs
        pnl_pct = net_pnl / (pos.entry_price * pos.quantity)
        
        self.current_capital += net_pnl
        self._update_drawdown()
        
        self.trades.append(TradeResult(
            trade_id=str(uuid.uuid4()),
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            quantity=pos.quantity,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            commission=pos.commission_paid + exit_commission,
            slippage=exit_slippage,
            exit_reason=reason,
            hold_duration=timestamp - pos.entry_time,
        ))

    async def _close_all_positions(self, data: pd.DataFrame):
        """Close all remaining positions at end of backtest."""
        last_price = data.iloc[-1]
        last_time = data.index[-1]
        
        for pos_id, pos in list(self.open_positions.items()):
            price_key = f"{pos.symbol}_close"
            if price_key in last_price:
                exit_price = last_price[price_key]
                await self._close_position_realistic(pos_id, exit_price, "end", data.index[-1])

    def _record_equity(self, timestamp: datetime):
        """Record current equity."""
        # Calculate unrealized PnL
        unrealized = 0
        for pos in self.open_positions.values():
            # Would need current price - simplified
            pass
        
        total_equity = self.current_capital + unrealized
        self.equity_curve.append((timestamp, total_equity))
        
        if total_equity > self.peak_capital:
            self.peak_capital = total_equity
        
        drawdown = (self.peak_capital - total_equity) / self.peak_capital
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def _update_drawdown(self):
        pass  # Done in _record_equity

    def _generate_report(self, run_id: str) -> BacktestReport:
        """Generate comprehensive backtest report."""
        trades_df = pd.DataFrame([t.__dict__ for t in self.trades]) if self.trades else pd.DataFrame()
        
        if not trades_df.empty:
            winning = trades_df[trades_df["pnl"] > 0]
            losing = trades_df[trades_df["pnl"] <= 0]
            
            metrics = {
                "total_trades": len(trades_df),
                "winning_trades": len(winning),
                "losing_trades": len(losing),
                "win_rate": len(winning) / len(trades_df) if len(trades_df) > 0 else 0,
                "total_pnl": trades_df["pnl"].sum(),
                "total_pnl_pct": (trades_df["pnl"] / self.config.initial_capital).sum(),
                "avg_win": winning["pnl"].mean() if len(winning) > 0 else 0,
                "avg_loss": losing["pnl"].mean() if len(losing) > 0 else 0,
                "profit_factor": abs(winning["pnl"].sum() / losing["pnl"].sum()) if len(losing) > 0 and losing["pnl"].sum() != 0 else float("inf"),
                "max_drawdown": self.max_drawdown,
                "sharpe_ratio": self._calculate_sharpe(),
                "sortino_ratio": self._calculate_sortino(),
                "calmar_ratio": (trades_df["pnl"].sum() / self.config.initial_capital) / self.max_drawdown if self.max_drawdown > 0 else float("inf"),
                "avg_hold_time": trades_df["hold_duration"].mean() if len(trades_df) > 0 else timedelta(0),
                "total_commission": trades_df["commission"].sum(),
                "total_slippage": trades_df["slippage"].sum(),
            }
        else:
            metrics = {
                "total_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "max_drawdown": 0,
            }
        
        return BacktestReport(
            run_id=run_id,
            config=self.config,
            trades=self.trades,
            equity_curve=self.equity_curve,
            metrics=metrics,
        )

    def _calculate_sharpe(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        equity = pd.Series([e for _, e in self.equity_curve])
        returns = equity.pct_change().dropna()
        if returns.std() == 0:
            return 0.0
        return (returns.mean() / returns.std()) * np.sqrt(252)

    def _calculate_sortino(self) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        equity = pd.Series([e for _, e in self.equity_curve])
        returns = equity.pct_change().dropna()
        downside = returns[returns < 0]
        if downside.std() == 0:
            return 0.0
        return (returns.mean() / downside.std()) * np.sqrt(252)


async def run_backtest(config: BacktestConfig) -> BacktestReport:
    """Convenience function to run a backtest."""
    engine = BacktestEngine(config)
    # In real usage, would fetch data from market data service
    # For now, return empty report
    return BacktestReport(
        run_id=str(uuid.uuid4()),
        config=config,
        trades=[],
        equity_curve=[],
        metrics={},
    )