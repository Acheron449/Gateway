from __future__ import annotations
import asyncio
from typing import Optional
from app.quant.impact_model import calculate_final_signal
from app.quant.risk_manager import RiskManager, RiskConfig
from app.services.broker_service import BrokerService, Order, OrderSide

class TradingOrchestrator:
    """
    The central hub that takes raw data, runs it through the models, checks risk,
    and sends executable orders to the broker.
    """
    def __init__(self, initial_capital: float, broker: BrokerService, risk_config: RiskConfig):
        self.broker = broker
        self.risk_manager = RiskManager(total_capital=initial_capital, config=risk_config)
        self.is_running = True

    async def process_market_data(self, raw_pattern_data: list[dict], sentiment_score: float):
        """
        Main entry point called when new market data arrives.
        """
        if not self.is_running:
            print("Orchestrator is stopped. No signals processed.")
            return

        # --- 1. Signal Generation (Impact Model) ---
        print("--- Starting Signal Generation ---")
        signal_analysis = calculate_final_signal(raw_pattern_data, sentiment_score)
        print(f"Model Output Signal: {signal_analysis}")

        if signal_analysis["direction"] == "Neutral":
            print("Signal is Neutral. No trading action required.")
            return

        # --- 2. Pre-Trade Risk Check & Sizing (Risk Manager) ---
        # NOTE: In a real system, volatility and current portfolio state are needed here.
        # Using placeholders for simulation:
        simulated_volatility = 0.02 
        
        # Calculate required size before sending to the model's side effect
        required_capital = self.risk_manager.calculate_position_size(
            current_price=100.0, # Placeholder entry price
            volatility=simulated_volatility
        )
        
        # Check overall portfolio health before proceeding
        if not self.risk_manager.validate_exposure(current_exposure=0.0, new_trade_value=required_capital):
            print("CRITICAL: Risk exposure limit reached. Halting trade sequence.")
            return

        # --- 3. Trade Construction & Execution ---
        side = OrderSide.BUY if signal_analysis["direction"] == "Bullish" else OrderSide.SELL
        
        # In a full system, we'd use the required_capital to derive the exact quantity
        # For now, we use a placeholder quantity matching the simulation above.
        order_to_send = Order(
            symbol="SAMPLE_STOCK",
            side=side,
            quantity=1.0, 
            entry_price=150.0, # Placeholder for the price when the signal fired
            order_type="MARKET"
        )
        
        print(f"--- Sending Order to Broker ---")
        broker_id = await self.broker.place_order(order_to_send)

        if broker_id:
            print(f"Order submitted successfully with Broker ID: {broker_id}")
            # TODO: Start monitoring this broker_id via get_order_status in a background task
        
        print("--- Signal Processing Cycle Complete ---")

# Example of how to run this (requires setting up async context):
# async def main():
#     broker = BrokerService("key", "secret")
#     risk_config = RiskConfig()
#     orchestrator = TradingOrchestrator(initial_capital=100000.0, broker=broker, risk_config=risk_config)
#     
#     # Simulate receiving a strong bullish signal
#     await orchestrator.process_market_data(
#         raw_pattern_data=[{"pattern": "Support_Breakout", "confidence": 0.9}], 
#         sentiment_score=0.8
#     )
# asyncio.run(main())