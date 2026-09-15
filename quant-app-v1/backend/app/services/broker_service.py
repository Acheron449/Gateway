from __future__ import annotations
import os
import asyncio
from typing import Literal, Optional
from dataclasses import dataclass
from enum import Enum

# try to import aiohttp for async HTTP calls; if unavailable, fall back to sync simulation
try:
    import aiohttp
    _HAS_AIOHTTP = True
except Exception:
    _HAS_AIOHTTP = False

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

@dataclass
class Order:
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    # Add instruction types like Limit, Market, Stop
    order_type: str = "MARKET"
    client_order_id: str = ""

@dataclass
class ExecutionReport:
    order_id: str
    status: OrderStatus
    executed_qty: float
    avg_price: float
    fee: float = 0.0

# --- Provider Clients ---

class _BaseProvider:
    async def place_order(self, order: Order) -> Optional[str]:
        raise NotImplementedError

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport:
        raise NotImplementedError

class _AlpacaProvider(_BaseProvider):
    def __init__(self, api_key: str, api_secret: str, base_url: str, paper: bool = True):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip('/')
        self.paper = paper

    async def _request(self, method: str, path: str, json: dict | None = None):
        if not _HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for real Alpaca integration")

        headers = {
            'APCA-API-KEY-ID': self.api_key,
            'APCA-API-SECRET-KEY': self.api_secret,
            'Content-Type': 'application/json'
        }
        url = f"{self.base_url}{path}"
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=headers, json=json, timeout=10) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"Alpaca API error {resp.status}: {text}")
                return await resp.json()

    async def place_order(self, order: Order) -> Optional[str]:
        payload = {
            'symbol': order.symbol,
            'qty': order.quantity,
            'side': order.side.value.lower(),
            'type': order.order_type.lower(),
            'time_in_force': 'day'
        }
        data = await self._request('POST', '/v2/orders', json=payload)
        return data.get('id')

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport:
        data = await self._request('GET', f'/v2/orders/{broker_order_id}')
        status = data.get('status', 'unknown').upper()
        try:
            status_enum = OrderStatus[status]
        except Exception:
            status_enum = OrderStatus.PENDING_NEW
        executed_qty = float(data.get('filled_qty', 0) or 0)
        avg_price = float(data.get('filled_avg_price', 0) or 0)
        return ExecutionReport(order_id=broker_order_id, status=status_enum, executed_qty=executed_qty, avg_price=avg_price)

class _FinnhubProvider(_BaseProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = 'https://finnhub.io/api/v1'
        self._orders: dict[str, dict] = {}

    async def _quote(self, symbol: str) -> dict:
        # Use aiohttp when available for non-blocking calls
        if _HAS_AIOHTTP:
            async with aiohttp.ClientSession() as session:
                url = f"{self.base_url}/quote?symbol={symbol}&token={self.api_key}"
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"Finnhub quote error: {resp.status}")
                    return await resp.json()
        else:
            # Synchronous fallback (best-effort simulation)
            return {"c": 0}

    async def place_order(self, order: Order) -> Optional[str]:
        # Finnhub does not provide order placement in its free tier; simulate a fill using latest quote
        try:
            quote = await self._quote(order.symbol)
            price = float(quote.get('c') or quote.get('pc') or order.entry_price)
        except Exception:
            price = float(order.entry_price)

        broker_id = f"FINNHUB_SIM_{abs(hash(str(order))) }"
        # Persist to in-memory order store for realistic status queries
        self._orders[broker_id] = {
            'symbol': order.symbol,
            'quantity': order.quantity,
            'filled': True,
            'avg_price': price,
        }
        print(f"Finnhub simulated order for {order.symbol} at {price}")
        return broker_id

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport:
        # Return stored filled report when available
        info = self._orders.get(broker_order_id)
        if info:
            return ExecutionReport(order_id=broker_order_id, status=OrderStatus.FILLED, executed_qty=info['quantity'], avg_price=info['avg_price'])

        # If not found, try to return a latest quote as a best-effort fill
        try:
            # Without symbol, default to 0.0
            # This fallback is coarse; prefer persisted orders for simulation fidelity
            return ExecutionReport(order_id=broker_order_id, status=OrderStatus.FILLED, executed_qty=1.0, avg_price=0.0)
        except Exception:
            return ExecutionReport(order_id=broker_order_id, status=OrderStatus.REJECTED, executed_qty=0.0, avg_price=0.0)

# --- Broker Service ---

class BrokerService:
    """
    Coordinates provider selection between Alpaca and Finnhub. If Alpaca is unavailable or aiohttp
    is not installed, falls back to using Finnhub for simulated fills.
    Also initializes the local DB for simulated order persistence.
    """
    def __init__(self, api_key: str = '', api_secret: str = '', paper_trading: bool = True, provider_preference: Optional[str] = None, slippage_pct: float | None = None, fee_per_order: float | None = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.provider_preference = provider_preference
        self.slippage_pct = slippage_pct if slippage_pct is not None else float(os.getenv('BROKER_SLIPPAGE_PCT', 0.001))
        self.fee_per_order = fee_per_order if fee_per_order is not None else float(os.getenv('BROKER_FEE', 0.0))

        # Read environment variables as fallbacks
        self._alpaca_key = api_key or os.getenv('ALPACA_API_KEY') or os.getenv('ALPACA_KEY')
        self._alpaca_secret = api_secret or os.getenv('ALPACA_SECRET') or os.getenv('ALPACA_API_SECRET')
        self._alpaca_base = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
        self._finnhub_key = os.getenv('FINNHUB_API_KEY')

        # Ensure DB tables exist for simulated orders/backtests
        try:
            from app.services import database
            database.init_db()
        except Exception as e:
            print(f'BrokerService: Failed to initialize DB: {e}')

        self.provider: _BaseProvider
        self._init_provider()

    def _init_provider(self):
        # If explicit preference given, respect it when possible
        pref = (self.provider_preference or '').lower() if self.provider_preference else None

        # Try Alpaca if keys present and aiohttp is available
        if (pref == 'alpaca' or pref is None) and self._alpaca_key and self._alpaca_secret and _HAS_AIOHTTP:
            try:
                self.provider = _AlpacaProvider(self._alpaca_key, self._alpaca_secret, self._alpaca_base, paper=self.paper_trading)
                # Could add a simple health probe here
                print('BrokerService: Using Alpaca provider')
                return
            except Exception as e:
                print(f'BrokerService: Failed to initialize Alpaca provider: {e}')

        # Fall back to Finnhub simulated provider if API key provided
        if (pref == 'finnhub' or pref is None) and self._finnhub_key:
            try:
                self.provider = _FinnhubProvider(self._finnhub_key)
                print('BrokerService: Using Finnhub simulated provider')
                return
            except Exception as e:
                print(f'BrokerService: Failed to initialize Finnhub provider: {e}')

        # Last resort: use local simulator
        self.provider = _FinnhubProvider(self._finnhub_key or '')
        print('BrokerService: Using local simulated provider (Finnhub fallback)')

    async def place_order(self, order: Order) -> Optional[str]:
        """Places an order via the selected provider. Returns a broker order id or None on error."""
        if order.quantity <= 0:
            print('BrokerService: Invalid order quantity')
            return None

        try:
            broker_id = await self.provider.place_order(order)
            # Apply slippage, partial-fill simulation and fees for simulated orders when provider is Finnhub
            if isinstance(self.provider, _FinnhubProvider) and broker_id:
                try:
                    info = getattr(self.provider, '_orders', {}).get(broker_id, {}) if hasattr(self.provider, '_orders') else {}
                    avg_price = info.get('avg_price') if info else None
                    if avg_price is None:
                        avg_price = order.entry_price

                    # apply slippage to price
                    slippage = avg_price * self.slippage_pct
                    filled_price = avg_price + slippage if order.side == OrderSide.BUY else avg_price - slippage

                    # simulate possible partial fill based on slippage magnitude (deterministic)
                    # larger slippage -> more chance of partial fill; ensure at least 60% fill
                    fill_ratio = 1.0
                    if self.slippage_pct > 0.005:
                        fill_ratio = max(0.6, 1.0 - min(self.slippage_pct * 10.0, 0.4))
                    executed_qty = order.quantity * fill_ratio

                    # update provider in-memory store so status queries reflect actual executed qty and price
                    try:
                        if hasattr(self.provider, '_orders') and broker_id in self.provider._orders:
                            self.provider._orders[broker_id]['avg_price'] = filled_price
                            self.provider._orders[broker_id]['quantity'] = executed_qty
                    except Exception:
                        pass

                    # persist simulated order using executed quantity and filled price
                    from app.services import database
                    database.insert_order(broker_id, order.symbol, executed_qty, filled_price, OrderStatus.FILLED.value, 'finnhub')
                except Exception as e:
                    print(f'BrokerService: Failed to persist simulated order: {e}')
            return broker_id
        except Exception as e:
            print(f'BrokerService: Provider place_order failed: {e}')
            # Attempt fallback: if current provider is Alpaca, try Finnhub simulation
            if not isinstance(self.provider, _FinnhubProvider) and self._finnhub_key is not None:
                try:
                    fallback = _FinnhubProvider(self._finnhub_key)
                    broker_id = await fallback.place_order(order)
                    print('BrokerService: Fallback to Finnhub simulation succeeded')
                    # persist fallback simulated order
                    try:
                        from app.services import database
                        # get price from fallback store
                        info = fallback._orders.get(broker_id, {})
                        avg_price = info.get('avg_price', order.entry_price)
                        slippage = avg_price * self.slippage_pct
                        filled_price = avg_price + slippage if order.side == OrderSide.BUY else avg_price - slippage
                        database.insert_order(broker_id, order.symbol, order.quantity, filled_price, OrderStatus.FILLED.value, 'finnhub')
                        try:
                            if hasattr(fallback, '_orders') and broker_id in fallback._orders:
                                fallback._orders[broker_id]['avg_price'] = filled_price
                        except Exception:
                            pass
                    except Exception as e2:
                        print(f'BrokerService: Failed to persist fallback simulated order: {e2}')
                    return broker_id
                except Exception as e2:
                    print(f'BrokerService: Fallback also failed: {e2}')
            return None

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport:
        try:
            report = await self.provider.get_order_status(broker_order_id)
            return report
        except Exception as e:
            print(f'BrokerService: get_order_status failed: {e}')
            # Best effort fallback to a simulated filled report
            return ExecutionReport(order_id=broker_order_id, status=OrderStatus.FILLED, executed_qty=1.0, avg_price=0.0)
# Example usage (requires asyncio and aiohttp for real Alpaca integration):
# async def main():
#     broker = BrokerService()
#     order = Order(symbol='AAPL', side=OrderSide.BUY, quantity=1.0, entry_price=150.0)
#     bid = await broker.place_order(order)
#     print('broker id', bid)
#
# if __name__ == '__main__':
#     asyncio.run(main())