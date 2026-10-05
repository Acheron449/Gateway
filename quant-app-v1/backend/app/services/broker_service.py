from __future__ import annotations
import math
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


class OrderValidationError(ValueError):
    """An order is malformed or attempts an unsupported execution mode."""


_PLACEHOLDER_SYMBOLS = {"", "TICK", "SAMPLE_STOCK", "SYMBOL", "PLACEHOLDER", "N/A"}

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

# --- Broker Service ---

class BrokerService:
    """Coordinates supported paper broker providers without silent fallbacks."""

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        paper_trading: bool = True,
        provider_preference: Optional[str] = None,
        slippage_pct: float | None = None,
        fee_per_order: float | None = None,
    ) -> None:
        if not paper_trading:
            raise OrderValidationError("Live execution is unavailable. Gateway only supports paper mode.")
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.provider_preference = provider_preference
        self.slippage_pct = slippage_pct if slippage_pct is not None else float(os.getenv("BROKER_SLIPPAGE_PCT", 0.001))
        self.fee_per_order = fee_per_order if fee_per_order is not None else float(os.getenv("BROKER_FEE", 0.0))

        self._alpaca_key = api_key or os.getenv("ALPACA_API_KEY") or os.getenv("ALPACA_KEY")
        self._alpaca_secret = api_secret or os.getenv("ALPACA_SECRET") or os.getenv("ALPACA_API_SECRET")
        self._alpaca_base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        if "paper-api.alpaca.markets" not in self._alpaca_base:
            raise OrderValidationError("ALPACA_BASE_URL must be Alpaca's paper endpoint during Phase 0")

        try:
            from app.services import database

            database.init_db()
        except Exception as exc:
            print(f"BrokerService: Failed to initialize DB: {exc}")

        self.provider: _BaseProvider | None = None
        self.provider_error = "No supported paper broker configured"
        self._init_provider()

    def _init_provider(self) -> None:
        pref = (self.provider_preference or "").strip().lower() if self.provider_preference else None
        if pref not in (None, "alpaca"):
            self.provider_error = f"Unsupported broker provider preference: {pref}"
            return
        if not (self._alpaca_key and self._alpaca_secret and _HAS_AIOHTTP):
            self.provider_error = "Alpaca paper credentials and aiohttp are required"
            return
        try:
            self.provider = _AlpacaProvider(
                self._alpaca_key,
                self._alpaca_secret,
                self._alpaca_base,
                paper=self.paper_trading,
            )
            print("BrokerService: Using Alpaca provider")
        except Exception as exc:
            self.provider_error = f"Failed to initialize Alpaca provider: {exc}"
            print(f"BrokerService: {self.provider_error}")

    async def place_order(self, order: Order) -> Optional[str]:
        """Place an order through the configured paper broker."""
        self._validate_order(order)
        if self.provider is None:
            raise OrderValidationError(self.provider_error)
        try:
            broker_id = await self.provider.place_order(order)
        except Exception as exc:
            raise OrderValidationError(f"Paper broker order failed: {exc}") from exc
        if not broker_id:
            raise OrderValidationError("Paper broker did not return an order id")
        return broker_id

    @staticmethod
    def _validate_order(order: Order) -> None:
        symbol = order.symbol.strip().upper() if isinstance(order.symbol, str) else ""
        if symbol in _PLACEHOLDER_SYMBOLS or not symbol.isalnum() or len(symbol) > 12:
            raise OrderValidationError("A supported, non-placeholder US-equity symbol is required")
        if not isinstance(order.quantity, (int, float)) or not math.isfinite(order.quantity) or order.quantity <= 0:
            raise OrderValidationError("Order quantity must be a positive finite number")
        if not isinstance(order.entry_price, (int, float)) or not math.isfinite(order.entry_price) or order.entry_price <= 0:
            raise OrderValidationError("Order price must be a positive finite number")
        if order.side not in {OrderSide.BUY, OrderSide.SELL}:
            raise OrderValidationError("Order side must be BUY or SELL")

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport:
        if self.provider is None:
            raise OrderValidationError(self.provider_error)
        try:
            return await self.provider.get_order_status(broker_order_id)
        except Exception as exc:
            raise OrderValidationError(f"Paper broker status lookup failed: {exc}") from exc
