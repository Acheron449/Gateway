from __future__ import annotations

import hashlib
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _load_provenance() -> type:
    from app.models import Provenance
    return Provenance


_PROVENANCE: type | None = None


def Provenance_() -> type:
    global _PROVENANCE
    if _PROVENANCE is None:
        _PROVENANCE = _load_provenance()
    return _PROVENANCE


def _content_id(*, symbol: str, timestamp: datetime, payload: dict[str, Any]) -> str:
    raw = f"{symbol}:{timestamp.isoformat()}:{payload!r}"
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest[:16]).decode("ascii").rstrip("=")


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"


class RuleType(StrEnum):
    CONDITION = "condition"
    THRESHOLD = "threshold"
    PATTERN = "pattern"
    EVENT = "event"


@dataclass(frozen=True)
class _Rule:
    rule_type: RuleType
    condition: str
    params: dict[str, Any] = field(default_factory=dict)


class EntryRule(BaseModel):
    condition: str = Field(description="Rule expression that must be satisfied to enter")
    params: dict[str, Any] = Field(default_factory=dict, description="Rule parameters")
    rule_type: RuleType = RuleType.CONDITION
    confirmation_bars: int = Field(default=0, ge=0, description="Bars of confirmation required")


class ExitRule(BaseModel):
    condition: str = Field(description="Rule expression that triggers exit")
    params: dict[str, Any] = Field(default_factory=dict)
    rule_type: RuleType = RuleType.CONDITION
    time_stop_bars: int = Field(default=0, ge=0)


class SizingRule(BaseModel):
    mode: Literal["fixed", "pct_equity", "volatility_target"] = Field(description="Sizing method")
    amount: float = Field(default=1.0, description="Sizing amount (units, pct, or vol target)")
    max_position_pct: float = Field(default=1.0, ge=0, le=1.0, description="Max position as fraction of equity")


class InvalidationRule(BaseModel):
    stop_loss: float | None = Field(default=None, description="Stop loss price or pct")
    time_stop: str | None = Field(default=None, description="Time-based stop (e.g. '2026-01-01T00:00:00Z')")
    event_stop: str | None = Field(default=None, description="Event-triggered stop (event id or pattern)")


class SessionRule(BaseModel):
    session: Literal["RTH", "ETH", "custom"] = Field(description="Session type")
    start: str | None = Field(default=None, description="Session start time (HH:MM or ISO)")
    end: str | None = Field(default=None, description="Session end time")
    days: list[str] = Field(default_factory=list, description="Active days of week (Mon..Sun)")


class EventRule(BaseModel):
    action: Literal["avoid", "require"] = Field(description="Avoid or require around events")
    event_type: str = Field(description="Event category (e.g. earnings, fomc)")
    window_minutes: int = Field(default=60, ge=0, description="Minutes around event to apply rule")


class Assumptions(BaseModel):
    commission: float = Field(default=0.0, ge=0, description="Commission per share or contract")
    spread: float = Field(default=0.0, ge=0, description="Expected spread in price units")
    slippage: float = Field(default=0.0, ge=0, description="Expected slippage in price units")
    latency_ms: int = Field(default=0, ge=0, description="Simulated execution latency in ms")
    fx: float = Field(default=1.0, description="FX rate to base currency (1.0 for USD)")
    corp_actions: bool = Field(default=False, description="Apply corporate actions in replay")


class StrategySpec(BaseModel):
    model_config = {"extra": "forbid", "validate_default": True}

    asset_universe: list[str] = Field(description="Symbols or catalogue query")
    timeframe: Timeframe = Field(description="Chart timeframe")
    entry: EntryRule
    exit: ExitRule
    sizing: SizingRule
    invalidation: InvalidationRule
    sessions: list[SessionRule] = Field(default_factory=list)
    event_rules: list[EventRule] = Field(default_factory=list)
    assumptions: Assumptions = Field(default_factory=Assumptions)
    labels: dict[str, str] = Field(default_factory=dict, description="Human-readable descriptions")

    id: str = Field(default="", description="Content-addressed ID (hash of inputs)")
    provenance: Any = Field(default=None, description="Provenance of the spec source")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("id", mode="before")
    @classmethod
    def _content_address(cls, v: str | None, info: Any) -> str:
        if v and v != "":
            return v
        payload = info.data
        return _content_id(
            symbol=",".join(payload.get("asset_universe", [])),
            timestamp=datetime.now(timezone.utc),
            payload={k: v for k, v in payload.items() if k != "id" and k != "provenance" and k != "created_at"},
        )
