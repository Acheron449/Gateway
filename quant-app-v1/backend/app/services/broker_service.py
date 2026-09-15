from __future__ import annotations
from typing import Literal, Optional
from dataclasses import dataclass
from enum import Enum

# --- Enums and Data Structures ---

class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, Enum):
    PENDING_NEW = "PENDING_NEW"
    ACCEPTED = "ACCEPTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

@dataclasses.dataclass
class Order:
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    # Add instruction types like Limit, Market, Stop
    order_type: str = "MARKET" 
    client_order_id: str = ""

@dataclasses.dataclass
class ExecutionReport:
    order_id: str
    status: OrderStatus
    executed_qty: float
    avg_price: float
    fee: float = 0.0

# --- Broker Service ---

class BrokerService:
    """
    Abstracts away the specifics of the external broker API (e.g., Alpaca, Interactive Brokers).
    All communication goes through this class.
    """
    def __init__(self, api_key: str, api_secret: str, paper_trading: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        print(f"Broker Service Initialized. Running in {'Paper Trading' if paper_trading else 'LIVE'} mode.")

    async def place_order(self, order: Order) -> Optional[str]:
        """
        Sends a new order to the broker. Returns the unique broker order ID on success.
        """
        print(f"Attempting to place {order.side.value} order for {order.quantity} of {order.symbol}...")
        # --- REAL API CALL GOES HERE ---
        # In a real system, this would involve async HTTP requests and proper error handling.
        if order.quantity <= 0:
            print("Error: Order quantity must be positive.")
            return None
        
        # Simulate successful placement and return a unique ID
        broker_id = f"BROKER_ID_{hash(str(order))}"
        print(f"Successfully placed order. Broker ID: {broker_id}")
        return broker_id

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport:
        """
        Polls the broker for the current status of a specific order.
        """
        print(f"Polling status for Broker ID: {broker_order_id}...")
        # Simulate response delay
        await asyncio.sleep(0.1) 
        
        # Simulate a successful fill for demonstration
        return ExecutionReport(
            order_id=broker_order_id,
            status=OrderStatus.FILLED,
            executed_qty=1.0,
            avg_price=150.0
        )

# Example usage (requires asyncio for simulation):
# import asyncio
# async def main():
#     broker = BrokerService("key", "secret")
#     new_order = Order(symbol="TSLA", side=OrderSide.BUY, quantity=1.0, entry_price=200.0)
#     broker_id = await broker.place_order(new_order)
#     if broker_id:
#         report = await broker.get_order_status(broker_id)
#         print(f"Final Report: {report.status}")
# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(main())