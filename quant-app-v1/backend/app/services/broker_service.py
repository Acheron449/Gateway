from __future__ import annotations
import math
import os
from typing import Optional
from urllib.parse import urlsplit
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
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REPLACED = "REPLACED"
    PENDING_CANCEL = "PENDING_CANCEL"
    PENDING_REPLACE = "PENDING_REPLACE"
    DONE_FOR_DAY = "DONE_FOR_DAY"
    ACCEPTED_FOR_BIDDING = "ACCEPTED_FOR_BIDDING"
    STOPPED = "STOPPED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    CALCULATED = "CALCULATED"
    UNKNOWN = "UNKNOWN"


_ALPACA_ORDER_STATUSES = {
    "new": OrderStatus.NEW,
    "accepted": OrderStatus.ACCEPTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "cancelled": OrderStatus.CANCELLED,
    "expired": OrderStatus.EXPIRED,
    "replaced": OrderStatus.REPLACED,
    "pending_cancel": OrderStatus.PENDING_CANCEL,
    "pending_replace": OrderStatus.PENDING_REPLACE,
    "done_for_day": OrderStatus.DONE_FOR_DAY,
    "accepted_for_bidding": OrderStatus.ACCEPTED_FOR_BIDDING,
    "stopped": OrderStatus.STOPPED,
    "rejected": OrderStatus.REJECTED,
    "suspended": OrderStatus.SUSPENDED,
    "calculated": OrderStatus.CALCULATED,
    "pending_new": OrderStatus.PENDING_NEW,
}


def _map_alpaca_order_status(value: object) -> OrderStatus:
    return _ALPACA_ORDER_STATUSES.get(str(value or "").strip().lower(), OrderStatus.UNKNOWN)


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

_PAPER_TRADING_ORIGIN = "https://paper-api.alpaca.markets"


def _validate_paper_trading_origin(base_url: str) -> str:
    """Accept only Alpaca's exact HTTPS paper API origin, without URL extras."""
    try:
        parsed = urlsplit(base_url)
        valid = (
            parsed.scheme == "https"
            and parsed.hostname == "paper-api.alpaca.markets"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise OrderValidationError("Broker execution requires Alpaca's exact HTTPS paper API origin")
    return _PAPER_TRADING_ORIGIN


class _AlpacaProvider(_BaseProvider):
    def __init__(self, api_key: str, api_secret: str, base_url: str = _PAPER_TRADING_ORIGIN, paper: bool = True):
        if not paper:
            raise OrderValidationError("Broker execution requires paper mode")
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = _validate_paper_trading_origin(base_url)
        self.paper = True

    def _url(self, path: str) -> str:
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "?" in path or "#" in path:
            raise OrderValidationError("Broker request path must be an absolute API path without query or fragment")
        url = f"{self.base_url}{path}"
        # Revalidate the assembled URL on every call to prevent a mutated base
        # URL or request-target path from escaping the paper origin.
        try:
            parts = urlsplit(url)
            origin = parts._replace(path="", query="", fragment="").geturl()
        except ValueError as exc:
            raise OrderValidationError("Invalid broker request URL") from exc
        _validate_paper_trading_origin(origin)
        return url

    async def _request(self, method: str, path: str, json: dict | None = None):
        if not _HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for real Alpaca integration")

        headers = {
            'APCA-API-KEY-ID': self.api_key,
            'APCA-API-SECRET-KEY': self.api_secret,
            'Content-Type': 'application/json'
        }
        url = self._url(path)
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=headers, json=json, timeout=10, allow_redirects=False
            ) as resp:
                text = await resp.text()
                if 300 <= resp.status < 400:
                    raise RuntimeError(f"Alpaca API redirect refused ({resp.status})")
                if resp.status >= 400:
                    raise RuntimeError(f"Alpaca API error {resp.status}: {text}")
                if not text:
                    return {}
                return await resp.json()

    async def place_order(self, order: Order) -> Optional[str]:
        raise OrderValidationError(
            "Broker order submission is unavailable until durable intent and recovery are integrated"
        )

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport:
        data = await self._request('GET', f'/v2/orders/{broker_order_id}')
        status_enum = _map_alpaca_order_status(data.get("status"))
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
        configured_base = os.getenv("ALPACA_BASE_URL", _PAPER_TRADING_ORIGIN)
        self._alpaca_base = _validate_paper_trading_origin(configured_base)

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
