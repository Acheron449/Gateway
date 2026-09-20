from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Optional
from uuid import UUID

import aiohttp

from app.services.broker_service import Order, OrderSide, OrderStatus, ExecutionReport, _BaseProvider, _AlpacaProvider


class LiveOrderStatus(str, Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    DONE_FOR_DAY = "done_for_day"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REPLACED = "replaced"
    PENDING_CANCEL = "pending_cancel"
    PENDING_REPLACE = "pending_replace"
    ACCEPTED = "accepted"
    PENDING_NEW = "pending_new"
    ACCEPTED_FOR_BIDDING = "accepted_for_bidding"
    STOPPED = "stopped"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    CALCULATED = "calculated"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    TRAILING_STOP = "trailing_stop"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    OPG = "opg"
    CLS = "cls"
    IOC = "ioc"
    FOK = "fok"


@dataclass(frozen=True, slots=True)
class LiveOrder:
    id: str
    client_order_id: str
    created_at: datetime
    updated_at: datetime
    submitted_at: Optional[datetime]
    filled_at: Optional[datetime]
    expired_at: Optional[datetime]
    canceled_at: Optional[datetime]
    failed_at: Optional[datetime]
    replaced_at: Optional[datetime]
    replaced_by: Optional[str]
    replaces: Optional[str]
    asset_id: str
    symbol: str
    asset_class: str
    notional: Optional[float]
    qty: float
    filled_qty: float
    filled_avg_price: Optional[float]
    order_type: OrderType
    type: str
    side: OrderSide
    time_in_force: TimeInForce
    limit_price: Optional[float]
    stop_price: Optional[float]
    trail_price: Optional[float]
    trail_percent: Optional[float]
    hwm: Optional[float]
    status: LiveOrderStatus
    extended_hours: bool
    legs: Optional[list]


@dataclass(frozen=True, slots=True)
class LivePosition:
    asset_id: str
    symbol: str
    exchange: str
    asset_class: str
    avg_entry_price: float
    qty: float
    avail_qty: float
    market_value: float
    cost_basis: float
    unrealized_pl: float
    unrealized_plpc: float
    unrealized_intraday_pl: float
    unrealized_intraday_plpc: float
    current_price: float
    lastday_price: float
    change_today: float


@dataclass(frozen=True, slots=True)
class LiveAccount:
    id: str
    account_number: str
    status: str
    currency: str
    cash: float
    portfolio_value: float
    pattern_day_trader: bool
    trading_blocked: bool
    transfers_blocked: bool
    account_blocked: bool
    created_at: datetime
    trade_suspended_by_user: bool
    multiplier: str
    equity: float
    last_equity: float
    long_market_value: float
    short_market_value: float
    initial_margin: float
    maintenance_margin: float
    last_maintenance_margin: float
    sma: float
    daytrade_count: int
    buying_power: float
    reg_t_buying_power: float
    daytrading_buying_power: float
    non_marginable_buying_power: float


@dataclass
class IdempotencyKey:
    key: str
    broker_order_id: Optional[str]
    created_at: datetime
    expires_at: datetime
    used: bool = False


class IdempotencyStore:
    """In-memory idempotency store with TTL. Replace with Redis in production."""

    def __init__(self, ttl_seconds: int = 86400):
        self._store: dict[str, IdempotencyKey] = {}
        self.ttl_seconds = ttl_seconds

    def generate_key(self) -> str:
        """Generate a UUID v7-like idempotency key."""
        return str(uuid.uuid4())

    def store(self, key: str, broker_order_id: Optional[str] = None) -> IdempotencyKey:
        now = datetime.now(timezone.utc)
        entry = IdempotencyKey(
            key=key,
            broker_order_id=broker_order_id,
            created_at=now,
            expires_at=now.replace(second=now.second + self.ttl_seconds),
            used=broker_order_id is not None,
        )
        self._store[key] = entry
        return entry

    def get(self, key: str) -> Optional[IdempotencyKey]:
        entry = self._store.get(key)
        if entry and entry.expires_at < datetime.now(timezone.utc):
            del self._store[key]
            return None
        return entry

    def mark_used(self, key: str, broker_order_id: str) -> bool:
        entry = self.get(key)
        if entry:
            entry.used = True
            entry.broker_order_id = broker_order_id
            return True
        return False

    def cleanup(self):
        now = datetime.now(timezone.utc)
        expired = [k for k, v in self._store.items() if v.expires_at < now]
        for k in expired:
            del self._store[k]


_idempotency_store = IdempotencyStore()


class AlpacaLiveProvider(_BaseProvider):
    """Alpaca live trading provider with idempotency, partial fills, and reconciliation."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://api.alpaca.markets",
        paper: bool = False,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip('/')
        self.paper = paper
        self._session: Optional[aiohttp.ClientSession] = None
        self._rate_limit_remaining = 200
        self._rate_limit_reset = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict:
        return {
            'APCA-API-KEY-ID': self.api_key,
            'APCA-API-SECRET-KEY': self.api_secret,
            'Content-Type': 'application/json',
        }

    async def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        session = await self._get_session()
        headers = self._headers()
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key

        url = f"{self.base_url}{path}"

        for attempt in range(3):
            try:
                async with session.request(method, url, headers=headers, json=json) as resp:
                    self._rate_limit_remaining = int(resp.headers.get('X-RateLimit-Remaining', '200'))
                    self._rate_limit_reset = int(resp.headers.get('X-RateLimit-Reset', '0'))

                    text = await resp.text()
                    if resp.status >= 400:
                        if resp.status == 429:
                            await asyncio.sleep(1 * (attempt + 1))
                            continue
                        raise RuntimeError(f"Alpaca API error {resp.status}: {text}")

                    if not text:
                        return {}
                    return await resp.json()

            except aiohttp.ClientError as e:
                if attempt == 2:
                    raise RuntimeError(f"Alpaca request failed after 3 attempts: {e}")
                await asyncio.sleep(0.5 * (attempt + 1))

        raise RuntimeError("Alpaca request failed")

    async def place_order(
        self,
        order: Order,
        idempotency_key: str | None = None,
        extended_hours: bool = False,
    ) -> Optional[str]:
        """Place a live order with idempotency key."""
        if idempotency_key is None:
            idempotency_key = _idempotency_store.generate_key()

        existing = _idempotency_store.get(idempotency_key)
        if existing and existing.used:
            return existing.broker_order_id

        payload = {
            'symbol': order.symbol,
            'qty': order.quantity,
            'side': order.side.value.lower(),
            'type': order.order_type.lower(),
            'time_in_force': 'day',
            'extended_hours': extended_hours,
        }

        if order.order_type in ('limit', 'stop_limit') and order.limit_price:
            payload['limit_price'] = round(order.limit_price, 2)
        if order.order_type in ('stop', 'stop_limit') and order.stop_price:
            payload['stop_price'] = round(order.stop_price, 2)

        data = await self._request('POST', '/v2/orders', json=payload, idempotency_key=idempotency_key)
        broker_order_id = data.get('id')

        if broker_order_id:
            _idempotency_store.mark_used(idempotency_key, broker_order_id)

        return broker_order_id

    async def get_order_status(self, broker_order_id: str) -> ExecutionReport:
        data = await self._request('GET', f'/v2/orders/{broker_order_id}')

        status_str = data.get('status', 'unknown').lower()
        try:
            status = OrderStatus[status_str.upper()]
        except KeyError:
            status = OrderStatus.PENDING_NEW

        executed_qty = float(data.get('filled_qty', 0) or 0)
        avg_price = float(data.get('filled_avg_price', 0) or 0)

        return ExecutionReport(
            order_id=broker_order_id,
            status=status,
            executed_qty=executed_qty,
            avg_price=avg_price,
            fee=0.0,
        )

    async def get_order(self, broker_order_id: str) -> LiveOrder:
        data = await self._request('GET', f'/v2/orders/{broker_order_id}')
        return self._parse_order(data)

    async def cancel_order(self, broker_order_id: str) -> bool:
        try:
            await self._request('DELETE', f'/v2/orders/{broker_order_id}')
            return True
        except RuntimeError as e:
            if "404" in str(e):
                return False
            raise

    async def cancel_all_orders(self) -> list[str]:
        data = await self._request('DELETE', '/v2/orders')
        return [o.get('id') for o in data] if isinstance(data, list) else []

    async def list_orders(
        self,
        status: str | None = None,
        limit: int = 500,
        after: datetime | None = None,
        until: datetime | None = None,
        direction: str = "desc",
    ) -> list[LiveOrder]:
        params = {'limit': str(limit), 'direction': direction, 'nested': 'true'}
        if status:
            params['status'] = status
        if after:
            params['after'] = after.isoformat()
        if until:
            params['until'] = until.isoformat()

        query = '&'.join(f"{k}={v}" for k, v in params.items())
        data = await self._request('GET', f'/v2/orders?{query}')

        return [self._parse_order(o) for o in data] if isinstance(data, list) else []

    async def get_account(self) -> LiveAccount:
        data = await self._request('GET', '/v2/account')
        return self._parse_account(data)

    async def get_positions(self) -> list[LivePosition]:
        data = await self._request('GET', '/v2/positions')
        return [self._parse_position(p) for p in data] if isinstance(data, list) else []

    async def get_position(self, symbol: str) -> LivePosition:
        data = await self._request('GET', f'/v2/positions/{symbol}')
        return self._parse_position(data)

    async def get_activities(
        self,
        activity_type: str = "FILL",
        after: datetime | None = None,
        until: datetime | None = None,
        direction: str = "desc",
        page_size: int = 100,
    ) -> list[dict]:
        params = {'activity_type': activity_type, 'direction': direction, 'page_size': str(page_size)}
        if after:
            params['after'] = after.isoformat()
        if until:
            params['until'] = until.isoformat()

        query = '&'.join(f"{k}={v}" for k, v in params.items())
        data = await self._request('GET', f'/v2/account/activities?{query}')
        return data if isinstance(data, list) else []

    def _parse_order(self, data: dict) -> LiveOrder:
        def parse_dt(key: str) -> Optional[datetime]:
            val = data.get(key)
            if val:
                return datetime.fromisoformat(val.replace('Z', '+00:00'))
            return None

        return LiveOrder(
            id=data.get('id', ''),
            client_order_id=data.get('client_order_id', ''),
            created_at=parse_dt('created_at') or datetime.now(timezone.utc),
            updated_at=parse_dt('updated_at') or datetime.now(timezone.utc),
            submitted_at=parse_dt('submitted_at'),
            filled_at=parse_dt('filled_at'),
            expired_at=parse_dt('expired_at'),
            canceled_at=parse_dt('canceled_at'),
            failed_at=parse_dt('failed_at'),
            replaced_at=parse_dt('replaced_at'),
            replaced_by=data.get('replaced_by'),
            replaces=data.get('replaces'),
            asset_id=data.get('asset_id', ''),
            symbol=data.get('symbol', ''),
            asset_class=data.get('asset_class', 'us_equity'),
            notional=data.get('notional'),
            qty=float(data.get('qty', 0)),
            filled_qty=float(data.get('filled_qty', 0)),
            filled_avg_price=float(data.get('filled_avg_price', 0)) if data.get('filled_avg_price') else None,
            order_type=OrderType(data.get('order_type', 'market')),
            type=data.get('type', 'market'),
            side=OrderSide(data.get('side', 'buy').upper()),
            time_in_force=TimeInForce(data.get('time_in_force', 'day')),
            limit_price=float(data['limit_price']) if data.get('limit_price') else None,
            stop_price=float(data['stop_price']) if data.get('stop_price') else None,
            trail_price=float(data['trail_price']) if data.get('trail_price') else None,
            trail_percent=float(data['trail_percent']) if data.get('trail_percent') else None,
            hwm=float(data['hwm']) if data.get('hwm') else None,
            status=LiveOrderStatus(data.get('status', 'new')),
            extended_hours=data.get('extended_hours', False),
            legs=data.get('legs'),
        )

    def _parse_account(self, data: dict) -> LiveAccount:
        def f(key: str) -> float:
            return float(data.get(key, 0) or 0)

        return LiveAccount(
            id=data.get('id', ''),
            account_number=data.get('account_number', ''),
            status=data.get('status', ''),
            currency=data.get('currency', 'USD'),
            cash=f('cash'),
            portfolio_value=f('portfolio_value'),
            pattern_day_trader=data.get('pattern_day_trader', False),
            trading_blocked=data.get('trading_blocked', False),
            transfers_blocked=data.get('transfers_blocked', False),
            account_blocked=data.get('account_blocked', False),
            created_at=datetime.fromisoformat(data['created_at'].replace('Z', '+00:00')),
            trade_suspended_by_user=data.get('trade_suspended_by_user', False),
            multiplier=data.get('multiplier', '1'),
            equity=f('equity'),
            last_equity=f('last_equity'),
            long_market_value=f('long_market_value'),
            short_market_value=f('short_market_value'),
            initial_margin=f('initial_margin'),
            maintenance_margin=f('maintenance_margin'),
            last_maintenance_margin=f('last_maintenance_margin'),
            sma=f('sma'),
            daytrade_count=int(data.get('daytrade_count', 0)),
            buying_power=f('buying_power'),
            reg_t_buying_power=f('reg_t_buying_power'),
            daytrading_buying_power=f('daytrading_buying_power'),
            non_marginable_buying_power=f('non_marginable_buying_power'),
        )

    def _parse_position(self, data: dict) -> LivePosition:
        def f(key: str) -> float:
            return float(data.get(key, 0) or 0)

        return LivePosition(
            asset_id=data.get('asset_id', ''),
            symbol=data.get('symbol', ''),
            exchange=data.get('exchange', ''),
            asset_class=data.get('asset_class', 'us_equity'),
            avg_entry_price=f('avg_entry_price'),
            qty=f('qty'),
            avail_qty=f('avail_qty'),
            market_value=f('market_value'),
            cost_basis=f('cost_basis'),
            unrealized_pl=f('unrealized_pl'),
            unrealized_plpc=f('unrealized_plpc'),
            unrealized_intraday_pl=f('unrealized_intraday_pl'),
            unrealized_intraday_plpc=f('unrealized_intraday_plpc'),
            current_price=f('current_price'),
            lastday_price=f('lastday_price'),
            change_today=f('change_today'),
        )


class ReconciliationJob:
    """Periodic reconciliation of local state vs broker."""

    def __init__(
        self,
        provider: AlpacaLiveProvider,
        local_get_positions,
        local_get_orders,
        tolerance_shares: float = 1.0,
        tolerance_cash_bps: float = 10.0,
    ):
        self.provider = provider
        self.local_get_positions = local_get_positions
        self.local_get_orders = local_get_orders
        self.tolerance_shares = tolerance_shares
        self.tolerance_cash_bps = tolerance_cash_bps
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.alerts: list[dict] = []

    async def run_once(self) -> dict:
        """Run one reconciliation cycle."""
        alerts = []

        local_positions = self.local_get_positions()
        broker_positions = await self.provider.get_positions()

        broker_by_symbol = {p.symbol: p for p in broker_positions}
        local_by_symbol = {p.get('instrument_id') or p.get('symbol'): p for p in local_positions}

        all_symbols = set(broker_by_symbol.keys()) | set(local_by_symbol.keys())

        for symbol in all_symbols:
            local = local_by_symbol.get(symbol)
            broker = broker_by_symbol.get(symbol)

            local_qty = float(local.get('quantity', 0)) if local else 0.0
            broker_qty = float(broker.qty) if broker else 0.0

            if abs(local_qty - broker_qty) > self.tolerance_shares:
                alerts.append({
                    'type': 'position_drift',
                    'symbol': symbol,
                    'local_qty': local_qty,
                    'broker_qty': broker_qty,
                    'difference': local_qty - broker_qty,
                    'threshold': self.tolerance_shares,
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                })

        local_cash = 0.0
        for p in local_positions:
            pass

        account = await self.provider.get_account()
        local_equity = sum(
            float(p.get('market_value', 0)) for p in local_positions
        ) + local_cash

        equity_diff_bps = abs(local_equity - account.equity) / max(account.equity, 1) * 10000
        if equity_diff_bps > self.tolerance_cash_bps:
            alerts.append({
                'type': 'equity_drift',
                'local_equity': local_equity,
                'broker_equity': account.equity,
                'difference_bps': equity_diff_bps,
                'threshold_bps': self.tolerance_cash_bps,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            })

        for alert in alerts:
            self.alerts.append(alert)

        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'position_alerts': len([a for a in alerts if a['type'] == 'position_drift']),
            'equity_alerts': len([a for a in alerts if a['type'] == 'equity_drift']),
            'alerts': alerts,
        }

    async def start(self, interval_seconds: int = 300):
        """Start periodic reconciliation."""
        if self._running:
            return

        self._running = True

        async def _loop():
            while self._running:
                try:
                    await self.run_once()
                except Exception as e:
                    self.alerts.append({
                        'type': 'reconciliation_error',
                        'error': str(e),
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                    })
                await asyncio.sleep(interval_seconds)

        self._task = asyncio.create_task(_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def get_alerts(self, since: datetime | None = None) -> list[dict]:
        if since:
            return [a for a in self.alerts if datetime.fromisoformat(a['timestamp'].replace('Z', '+00:00')) >= since]
        return self.alerts


def _quantize(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def generate_client_order_id() -> str:
    """Generate a UUID v7-like client order id for idempotency."""
    return str(uuid.uuid4())