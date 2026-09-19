from __future__ import annotations
import asyncio
from typing import Optional
from app.quant.impact_model import calculate_final_signal
from app.quant.risk_manager import RiskManager, RiskConfig
from app.services.broker_service import BrokerService

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

        # This legacy path has no reviewed symbol, price, quantity, account or
        # risk decision. It may produce research signals but must never create
        # an order from placeholders.
        print("Signal recorded as research only; an approved paper order is required.")
        return {"status": "draft_required", "signal": signal_analysis, "execution_mode": "paper"}

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
