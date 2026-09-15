from __future__ import annotations
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from app.quant.impact_model import calculate_final_signal
from app.quant.risk_manager import RiskManager, RiskConfig
from app.services.broker_service import BrokerService, Order, OrderSide, ExecutionReport
from datetime import datetime
from dataclasses import dataclass

# --- Data Structures for Backtesting ---

@dataclass
class BacktestResult:
    # Stores the outcome of a single trading idea/signal cycle
    signal_time: datetime
    symbol: Optional[str]
    signal_direction: str
    confidence: float
    entry_price: float
    exit_price: Optional[float] = None
    pnl_pct: float = 0.0
    outcome: str = "Open"

class BacktestEngine:
    """
    Runs simulation of trades against historical market data to evaluate strategy performance.
    Supports historical backtesting mode that uses the BrokerService to simulate fills (or real fills when Alpaca is configured).
    """
    def __init__(self, initial_capital: float, risk_config: RiskConfig):
        self.initial_capital = initial_capital
        self.risk_manager = RiskManager(total_capital=initial_capital, config=risk_config)
        self.trade_log: List[BacktestResult] = []
        self.current_capital = initial_capital
        # support multiple concurrent open positions keyed by an order id
        self.open_trades: Dict[str, dict] = {}

    async def run_simulation(self, historical_market_data: pd.DataFrame, broker: Optional[BrokerService] = None) -> List[BacktestResult]:
        """
        Runs the backtest over the provided historical_market_data. If a BrokerService is provided,
        it will be used to place simulated orders (Alpaca when available, Finnhub simulation otherwise).

        :param historical_market_data: DataFrame with columns ['Timestamp','Price','Sentiment_Score','Pattern_Features']
        :param broker: Optional BrokerService to simulate/place orders
        :return: List[BacktestResult]
        """
        print("--- Starting Backtesting Simulation ---")
        df = historical_market_data.reset_index(drop=True)
        n = len(df)

        for i in range(n):
            row = df.iloc[i]
            timestamp = row.get('Timestamp', None)
            current_price = float(row['Price'])
            sentiment_score = float(row.get('Sentiment_Score', 0.0))
            pattern_features = row.get('Pattern_Features', [])

            # 1. Signal generation
            signal_analysis = calculate_final_signal(pattern_features, sentiment_score)
            direction = signal_analysis.get('direction', 'Neutral')
            confidence = float(signal_analysis.get('confidence', 0.0))

            # Check open trades exits first (supporting multiple concurrent positions)
            if self.open_trades:
                closed_any = False
                for oid, ot in list(self.open_trades.items()):
                    # determine SL/TP hit
                    if ot['direction'] == 'Bullish':
                        if current_price <= ot['stop_loss']:
                            exit_price = ot['stop_loss']
                            outcome = 'Closed_SL'
                        elif current_price >= ot['take_profit']:
                            exit_price = ot['take_profit']
                            outcome = 'Closed_TP'
                        else:
                            exit_price = None
                    else:  # Short
                        if current_price >= ot['stop_loss']:
                            exit_price = ot['stop_loss']
                            outcome = 'Closed_SL'
                        elif current_price <= ot['take_profit']:
                            exit_price = ot['take_profit']
                            outcome = 'Closed_TP'
                        else:
                            exit_price = None

                    if exit_price is not None:
                        qty = ot['quantity']
                        entry_price = ot['entry_price']
                        position_value = entry_price * qty
                        if ot['direction'] == 'Bullish':
                            pnl_currency = (exit_price - entry_price) * qty
                        else:
                            pnl_currency = (entry_price - exit_price) * qty

                        # Account for fees (open + close) when calculating realized PnL
                        open_fee = ot.get('open_fee', 0.0)
                        close_fee = getattr(broker, 'fee_per_order', 0.0) if broker is not None else 0.0
                        total_fees = open_fee + close_fee

                        pnl_currency = pnl_currency - total_fees
                        pnl_pct = (pnl_currency / position_value) if position_value != 0 else 0.0
                        self.current_capital += pnl_currency

                        self.trade_log.append(BacktestResult(
                            signal_time=ot['signal_time'],
                            symbol=ot.get('symbol'),
                            signal_direction=ot['direction'],
                            confidence=ot['confidence'],
                            entry_price=entry_price,
                            exit_price=exit_price,
                            pnl_pct=pnl_pct,
                            outcome=outcome
                        ))

                        print(f"Trade {outcome} for {oid} at {exit_price}. PnL: {pnl_pct*100:.2f}% | New capital: {self.current_capital:.2f}")
                        # remove closed trade
                        del self.open_trades[oid]
                        closed_any = True
                # if any closed, move to next candle (simulates instantaneous reaction)
                if closed_any:
                    continue

            # Consider opening new positions (multi-position support)
            if direction in ("Bullish", "Bearish") and confidence > 0.0:
                # Estimate volatility from recent returns (14-period)
                window = 14
                start = max(0, i - window + 1)
                price_slice = df['Price'].iloc[start:i+1]
                if len(price_slice) >= 2:
                    returns = price_slice.pct_change().dropna()
                    vol = float(returns.std()) if not returns.empty else 0.01
                else:
                    vol = 0.01

                # Calculate capital to risk using RiskManager
                capital_to_use = self.risk_manager.calculate_position_size(current_price=current_price, volatility=vol)
                if capital_to_use <= 0:
                    continue

                # Enforce portfolio exposure limits
                current_exposure = sum((ot.get('entry_price', 0.0) * ot.get('quantity', 0.0)) for ot in self.open_trades.values())
                if not self.risk_manager.validate_exposure(current_total_exposure=current_exposure, new_trade_value=capital_to_use):
                    # Would exceed exposure limits
                    print(f"Skipping open: exposure limit reached (current {current_exposure:.2f}, requested {capital_to_use:.2f})")
                    continue

                quantity = capital_to_use / current_price
                if quantity <= 0:
                    continue

                side = OrderSide.BUY if direction == 'Bullish' else OrderSide.SELL
                order = Order(symbol=row.get('Symbol', 'TICK'), side=side, quantity=quantity, entry_price=current_price)

                broker_id = None
                fill_price = current_price
                try:
                    if broker is not None:
                        broker_id = await broker.place_order(order)
                        if broker_id:
                            report = await broker.get_order_status(broker_id)
                            if report:
                                if getattr(report, 'avg_price', 0) > 0:
                                    fill_price = report.avg_price
                                # respect executed quantity in case of partial fills
                                if getattr(report, 'executed_qty', 0) > 0:
                                    quantity = float(report.executed_qty)
                except Exception as exc:
                    print(f"Broker error during order placement: {exc}")
                    # fallback to market price
                    fill_price = current_price

                # compute SL/TP based on filled price
                dir_label = 'Long' if direction == 'Bullish' else 'Short'
                exits = self.risk_manager.get_exit_levels(fill_price, dir_label)

                # Determine an order id to key open_trades; prefer broker_id when available
                order_id = broker_id if broker_id else f"sim-{i}-{len(self.open_trades)+1}"

                self.open_trades[order_id] = {
                    'signal_time': timestamp,
                    'direction': direction,
                    'confidence': confidence,
                    'entry_price': fill_price,
                    'quantity': quantity,
                    'broker_id': broker_id,
                    'symbol': row.get('Symbol', 'TICK'),
                    'stop_loss': exits['stop_loss'],
                    'take_profit': exits['take_profit'],
                    'open_fee': getattr(broker, 'fee_per_order', 0.0) if broker is not None else 0.0,
                }

                print(f"Opened {direction} id={order_id} at {fill_price} qty={quantity:.6f} SL={exits['stop_loss']:.4f} TP={exits['take_profit']:.4f}")
                continue

        # End of series: close any remaining open positions at last price
        if self.open_trades:
            last_price = float(df['Price'].iloc[-1])
            for oid, ot in list(self.open_trades.items()):
                qty = ot['quantity']
                entry_price = ot['entry_price']
                if ot['direction'] == 'Bullish':
                    pnl_currency = (last_price - entry_price) * qty
                else:
                    pnl_currency = (entry_price - last_price) * qty
                position_value = entry_price * qty
                # account for fees when closing at series end
                open_fee = ot.get('open_fee', 0.0)
                close_fee = getattr(broker, 'fee_per_order', 0.0) if broker is not None else 0.0
                total_fees = open_fee + close_fee
                pnl_currency = pnl_currency - total_fees
                pnl_pct = (pnl_currency / position_value) if position_value != 0 else 0.0
                self.current_capital += pnl_currency
                self.trade_log.append(BacktestResult(
                    signal_time=ot['signal_time'],
                    symbol=ot.get('symbol'),
                    signal_direction=ot['direction'],
                    confidence=ot['confidence'],
                    entry_price=entry_price,
                    exit_price=last_price,
                    pnl_pct=pnl_pct,
                    outcome='Closed_End'
                ))
                print(f"Closing open trade {oid} at series end price {last_price}. PnL: {pnl_pct*100:.2f}%")
                del self.open_trades[oid]

        print("--- Backtest Run Finished ---")
        return self.trade_log

    def analyze_results(self, trade_logs: List[BacktestResult]) -> Dict[str, Any]:
        """
        Calculates key performance indicators (KPIs) from the executed trades.
        """
        if not trade_logs:
            return {"Error": "No trades executed to analyze."}

        successful_trades = [t for t in trade_logs if t.outcome.startswith("Closed") and t.pnl_pct > 0]
        failed_trades = [t for t in trade_logs if t.outcome.startswith("Closed") and t.pnl_pct <= 0]
        
        total_trades = len(trade_logs)
        win_rate = len(successful_trades) / total_trades if total_trades > 0 else 0.0

        total_pnl = sum(((t.pnl_pct or 0.0) * (t.entry_price or 0.0)) for t in trade_logs if t.entry_price)

        return {
            "Total Trades": total_trades,
            "Win Rate": f"{win_rate*100:.2f}%",
            "Winning Trades Count": len(successful_trades),
            "Losing Trades Count": len(failed_trades),
            "Total PnL (approx)": total_pnl,
            "TradeLog": trade_logs
        }

# --- Example Usage Simulation ---
if __name__ == "__main__":
    import asyncio

    # Setup simulation environment
    INITIAL_CAPITAL = 100000.0
    RISK_CONFIG = RiskConfig()

    # Dummy historical data simulating market ticks
    data = {
        'Timestamp': [datetime(2026, 9, 15)],
        'Price': [150.0],
        'Sentiment_Score': [0.5],
        # Pattern_Features structure mimics what is expected by calculate_final_signal
        'Pattern_Features': [
            [{"pattern": "Moving_Avg_Cross", "confidence": 0.6, "direction": "Bullish"}]
        ]
    }
    df = pd.DataFrame(data)

    # Run the test
    engine = BacktestEngine(initial_capital=INITIAL_CAPITAL, risk_config=RISK_CONFIG)
    results = asyncio.run(engine.run_simulation(df))
    
    # Analyze
    analysis = engine.analyze_results(results)
    print("\n--- BACKTEST ANALYSIS COMPLETE ---")
    print(analysis)