"""Typed domain records shared across Gateway's research and paper-trading paths.

Every provider-derived record carries ``Provenance`` so a consumer can always
answer "which source produced this, when, how fresh, and under what coverage".
These models describe the domain contract; provider adapters normalize into
these records and never expose raw vendor payloads.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from app.services.provenance import UTC_ISO


def _provider_record_id(provider: str, natural_key: str) -> str:
    digest = hashlib.sha256(f"{provider}:{natural_key}".encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest[:12]).decode("ascii").rstrip("=")


_PLACEHOLDER_SYMBOLS = {"", "TICK", "SAMPLE_STOCK", "SYMBOL", "PLACEHOLDER", "N/A"}


class Provenance(BaseModel):
    """Traceability metadata attached to every normalized provider record."""

    source: str = Field(description="Provider or catalogue identity, e.g. 'alpaca' or 'gateway-catalogue'")
    provider_version: str = Field(description="Version of the provider adapter or dataset that produced the record")
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC time the record reached Gateway")
    data_time: datetime | None = Field(default=None, description="UTC time the data describes; None when not applicable")
    coverage: str = Field(default="", description="Markets/asset classes and timeframe the record covers")
    delay_seconds: int | None = Field(default=None, description="Expected or observed data latency in seconds")
    entitlement: str = Field(default="configured-provider", description="Licence/entitlement level the record is served under")


def provenance_now(*, source: str, provider_version: str, coverage: str = "", delay_seconds: int | None = None, data_time: datetime | None = None) -> Provenance:
    """Build provenance stamped with the current UTC fetch time."""
    return Provenance(
        source=source,
        provider_version=provider_version,
        fetched_at=datetime.now(timezone.utc),
        data_time=data_time,
        coverage=coverage,
        delay_seconds=delay_seconds,
    )


class AssetClass(StrEnum):
    EQUITY = "equity"
    ETF = "etf"


class InstrumentType(StrEnum):
    COMMON_STOCK = "common_stock"
    ETF = "etf"
    INDEX = "index"


class Instrument(BaseModel):
    """A tradable/researchable instrument from the versioned Gateway catalogue."""

    symbol: str = Field(min_length=1, max_length=12, pattern=r"^[A-Z0-9.\-^]+$")
    name: str
    exchange: str = Field(description="Listing exchange, e.g. 'NASDAQ' or 'NYSE'")
    currency: str = "USD"
    asset_class: AssetClass = AssetClass.EQUITY
    instrument_type: InstrumentType = InstrumentType.COMMON_STOCK
    cik: str | None = Field(default=None, description="SEC Central Index Key when available")
    description: str | None = None
    provenance: Provenance

    @field_validator("symbol", mode="before")
    @classmethod
    def _normalize_symbol(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @property
    def domain(self) -> str:
        return "US-equities"


class Quote(BaseModel):
    """A normalized market quote (bid/ask/last) with freshness metadata."""

    instrument: str = Field(description="Catalogue symbol the quote belongs to")
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    change: float | None = None
    change_pct: float | None = None
    provenance: Provenance


class Candle(BaseModel):
    """A normalized OHLC(V) candle. ``raw`` is intentionally never included."""

    instrument: str
    timeframe: str = Field(description="Interval key, e.g. '1m', '1h', '1d'")
    time: datetime = Field(description="UTC bucket start of the candle")
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    trades: int | None = None
    provenance: Provenance


class NewsItem(BaseModel):
    """A publishable news story with source timestamps and entity tagging."""

    id: str = Field(description="Stable provider record id")
    headline: str
    url: str | None = None
    source: str
    published_at: datetime = Field(description="UTC publication time")
    fetched_at: datetime = Field(description="UTC time Gateway received the story")
    categories: list[str] = Field(default_factory=list)
    related_symbols: list[str] = Field(default_factory=list, description="Instruments referenced by the story")
    sentiment_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    provider_version: str = ""
    data_time: datetime | None = None
    coverage: str = ""
    delay_seconds: int | None = None
    entitlement: str = "configured-provider"
    tags: list[dict] = Field(default_factory=list, description="Derived event/entity tags")

    @property
    def age_seconds(self) -> float | None:
        return (datetime.now(timezone.utc) - self.fetched_at).total_seconds()


class EventImportance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EconomicEvent(BaseModel):
    """A scheduled economic release with UTC timestamps and revision history."""

    id: str = Field(description="Stable provider event id")
    title: str
    country: str
    currency: str = "USD"
    importance: EventImportance = EventImportance.MEDIUM
    scheduled_at: datetime = Field(description="UTC scheduled release time")
    actual: float | None = None
    forecast: float | None = None
    prior: float | None = None
    revisions: list[dict] = Field(default_factory=list, description="Chronological event revisions, oldest first")
    related_symbols: list[str] = Field(default_factory=list)
    provider_version: str = ""
    source: str = ""
    fetched_at: datetime | None = None
    data_time: datetime | None = None
    coverage: str = ""
    delay_seconds: int | None = None
    entitlement: str = "configured-provider"
    tags: list[dict] = Field(default_factory=list, description="Derived event/entity tags")


class StrategyStatus(StrEnum):
    DRAFT = "draft"
    TESTED = "tested"
    VALIDATED = "validated"
    PAPER = "paper"
    PAUSED = "paused"
    RETIRED = "retired"


class Strategy(BaseModel):
    """A named strategy container; rules live in immutable StrategyVersion records."""

    id: str
    name: str
    status: StrategyStatus = StrategyStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    versions: list[StrategyVersion] = Field(default_factory=list)


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"


class RuleType(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"
    SIZING = "sizing"
    INVALIDATION = "invalidation"
    SESSION = "session"
    EVENT = "event"


class BaseRule(BaseModel):
    """Base class for all rule types with common fields."""
    id: str
    type: RuleType
    description: str = ""
    enabled: bool = True
    priority: int = 0  # Higher priority rules evaluated first


class EntryRule(BaseRule):
    """A typed entry condition rule."""
    type: RuleType = RuleType.ENTRY
    # Condition expressed as a structured expression (e.g., for a rule engine)
    condition: dict = Field(default_factory=dict, description="Structured condition: {'indicator': 'RSI', 'operator': '<', 'value': 30}")
    # Legacy human-readable text (kept for backwards compatibility)
    text: str = ""


class ExitRule(BaseRule):
    """A typed exit condition rule."""
    type: RuleType = RuleType.EXIT
    condition: dict = Field(default_factory=dict)
    text: str = ""
    # Exit can be take-profit, stop-loss, or signal-based
    exit_type: str = "signal"  # "signal" | "take_profit" | "stop_loss" | "time"


class SizingRule(BaseRule):
    """A typed position sizing rule."""
    type: RuleType = RuleType.SIZING
    method: str = "fixed_fractional"  # "fixed_fractional" | "kelly" | "volatility_target" | "fixed_size"
    parameters: dict = Field(default_factory=dict, description="Method-specific params, e.g., {'risk_per_trade': 0.02}")
    text: str = ""


class InvalidationRule(BaseRule):
    """A typed invalidation/stop rule."""
    type: RuleType = RuleType.INVALIDATION
    condition: dict = Field(default_factory=dict)
    text: str = ""


class SessionRule(BaseRule):
    """A typed session/time window rule."""
    type: RuleType = RuleType.SESSION
    timezone: str = "UTC"
    allowed_sessions: list[str] = Field(default_factory=list, description="e.g., ['RTH', 'PRE', 'POST']")
    blocked_windows: list[dict] = Field(default_factory=list, description="e.g., [{'start': '14:30', 'end': '15:00'}]")
    text: str = ""


class EventRule(BaseRule):
    """A typed economic event rule."""
    type: RuleType = RuleType.EVENT
    event_importance: list[str] = Field(default_factory=list, description="e.g., ['high', 'medium']")
    blackout_minutes_before: int = 15
    blackout_minutes_after: int = 15
    allowed_currencies: list[str] = Field(default_factory=list)
    blocked_currencies: list[str] = Field(default_factory=list)
    text: str = ""


class Assumptions(BaseModel):
    """Cost and execution assumptions for a backtest."""
    commission_per_share: float = 0.005
    commission_min: float = 1.0
    spread_bps: float = 1.0  # bid-ask spread in basis points
    slippage_bps: float = 2.0  # expected slippage in basis points
    latency_ms: int = 50  # simulated order latency
    borrow_cost_annual_bps: float = 0.0  # for short positions
    funding_rate_bps: float = 0.0  # for leveraged positions


class StrategySpec(BaseModel):
    """A complete, versioned, typed strategy specification for the Strategy Studio."""
    strategy_id: str
    version: int = Field(ge=1)
    name: str
    description: str = ""
    universe: list[str] = Field(default_factory=list, description="Catalogue symbols")
    timeframe: Timeframe = Timeframe.H1
    entry_rules: list[EntryRule] = Field(default_factory=list)
    exit_rules: list[ExitRule] = Field(default_factory=list)
    sizing_rules: list[SizingRule] = Field(default_factory=list)
    invalidation_rules: list[InvalidationRule] = Field(default_factory=list)
    session_rules: list[SessionRule] = Field(default_factory=list)
    event_rules: list[EventRule] = Field(default_factory=list)
    assumptions: Assumptions = Field(default_factory=Assumptions)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str | None = None

    def to_legacy_version(self, strategy_id: str) -> "StrategyVersion":
        """Convert to legacy StrategyVersion for backwards compatibility."""
        return StrategyVersion(
            strategy_id=strategy_id,
            version=self.version,
            universe=self.universe,
            timeframe=self.timeframe.value,
            entry_rules=[r.text or str(r.condition) for r in self.entry_rules if r.enabled],
            exit_rules=[r.text or str(r.condition) for r in self.exit_rules if r.enabled],
            sizing_rules=[r.text or f"{r.method}:{r.parameters}" for r in self.sizing_rules if r.enabled],
            invalidation_rules=[r.text or str(r.condition) for r in self.invalidation_rules if r.enabled],
            session_rules=[r.text or f"{r.allowed_sessions}" for r in self.session_rules if r.enabled],
            event_rules=[r.text or f"{r.event_importance}" for r in self.event_rules if r.enabled],
            assumptions=self.assumptions.model_dump(),
        )


class StrategyVersion(BaseModel):
    """An immutable strategy specification snapshot that a backtest binds to."""

    strategy_id: str
    version: int = Field(ge=1)
    universe: list[str] = Field(default_factory=list, description="Catalogue symbols")
    timeframe: str = "1h"
    entry_rules: list[str] = Field(default_factory=list)
    exit_rules: list[str] = Field(default_factory=list)
    sizing_rules: list[str] = Field(default_factory=list)
    invalidation_rules: list[str] = Field(default_factory=list)
    session_rules: list[str] = Field(default_factory=list)
    event_rules: list[str] = Field(default_factory=list)
    assumptions: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BacktestRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BacktestRun(BaseModel):
    """A persisted backtest run with the full reproducibility receipt."""

    id: str
    strategy_version: int
    engine_version: str
    status: BacktestRunStatus = BacktestRunStatus.QUEUED
    start: datetime
    end: datetime
    data_source: str
    data_version: str
    event_snapshot_id: str | None = None
    cost_assumptions: dict = Field(default_factory=dict)
    parameters: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(StrEnum):
    PENDING_NEW = "pending_new"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order(BaseModel):
    """Canonical Gateway order record. Symbol/quantity/price must be reviewable values."""

    model_config = {"extra": "forbid", "validate_default": True}

    id: str = Field(description="Gateway order id")
    instrument: str = Field(min_length=1, description="Supported catalogue symbol (placeholder values rejected)")
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    quantity: float = Field(gt=0, description="Positive finite quantity")
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    account_id: str | None = None
    execution_mode: str = "paper"
    status: OrderStatus = OrderStatus.PENDING_NEW
    filled_qty: float = Field(default=0, ge=0, description="Quantity already filled")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("instrument")
    @classmethod
    def _non_placeholder_symbol(cls, value: str) -> str:
        symbol = value.strip().upper()
        if symbol in _PLACEHOLDER_SYMBOLS or "_" in symbol or not symbol.isalnum() or len(symbol) > 12:
            raise ValueError("A supported, non-placeholder US-equity symbol is required")
        return symbol

    @field_validator("execution_mode")
    @classmethod
    def _paper_only(cls, value: str) -> str:
        if value.lower() != "paper":
            raise ValueError("Order.execution_mode must be 'paper'; live execution is not available")
        return "paper"


class Fill(BaseModel):
    """A canonical executed fill for a paper order, traceable to origin and ledger state."""

    id: str
    order_id: str
    instrument: str
    side: OrderSide
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    commission: float = Field(default=0.0, ge=0)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    account_id: str | None = None


class Position(BaseModel):
    """An open ledger position within a Portfolio."""

    instrument: str
    quantity: float
    avg_price: float = Field(gt=0)
    realized_pnl: float = Field(default=0.0)
    unrealized_pnl: float = Field(default=0.0)


class Portfolio(BaseModel):
    """Canonical paper portfolio ledger: cash, positions, orders and fills."""

    id: str
    account_id: str = "paper"
    cash: float
    positions: list[Position] = Field(default_factory=list)
    orders: list[Order] = Field(default_factory=list)
    fills: list[Fill] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "AssetClass",
    "BacktestRun",
    "BacktestRunStatus",
    "Assumptions",
    "Candle",
    "EconomicEvent",
    "EntryRule",
    "EventImportance",
    "EventRule",
    "ExitRule",
    "Fill",
    "Instrument",
    "InstrumentType",
    "InvalidationRule",
    "NewsItem",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "Portfolio",
    "Position",
    "Provenance",
    "Quote",
    "SessionRule",
    "SizingRule",
    "Strategy",
    "StrategySpec",
    "StrategyStatus",
    "StrategyVersion",
    "Timeframe",
    "_provider_record_id",
    "provenance_now",
    "RuleType",
]