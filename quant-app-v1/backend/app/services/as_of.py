"""UTC timestamp parsing and upper-bound filtering for historical data."""

from __future__ import annotations

from datetime import datetime, timezone
import inspect
import math
from typing import Any, Callable, Iterable, Mapping


def supports_keyword_argument(function: Callable[..., Any], name: str) -> bool:
    """Whether a callable accepts a keyword without relying on trial calls."""
    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        (parameter.name == name and parameter.kind is not inspect.Parameter.POSITIONAL_ONLY)
        or parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )


def normalize_as_of(value: datetime | None) -> datetime | None:
    """Normalize an aware cutoff to UTC, rejecting ambiguous naive datetimes."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(timezone.utc)


def parse_data_timestamp(value: Any) -> datetime | None:
    """Parse Unix-second numbers or ISO-8601 values as aware UTC datetimes."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        timestamp = getattr(value, "timestamp", None)
        if not callable(timestamp):
            return None
        try:
            seconds = float(timestamp())
            if not math.isfinite(seconds):
                return None
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, TypeError, ValueError):
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def is_at_or_before(value: Any, as_of: datetime | None) -> bool:
    """Whether a record timestamp is admissible at an optional UTC cutoff."""
    cutoff = normalize_as_of(as_of)
    if cutoff is None:
        return True
    timestamp = parse_data_timestamp(value)
    return timestamp is not None and timestamp <= cutoff


def filter_timestamped_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime | None,
    timestamp_keys: tuple[str, ...] = ("time", "timestamp"),
) -> list[dict[str, Any]]:
    """Retain rows at/before a cutoff, dropping unknown-time rows when set.

    With no cutoff this is a shallow, order-preserving copy and deliberately
    keeps current callers' historical behavior, including malformed rows.
    """
    cutoff = normalize_as_of(as_of)
    copied = [dict(row) for row in rows]
    if cutoff is None:
        return copied

    filtered: list[dict[str, Any]] = []
    for row in copied:
        timestamp = next((row.get(key) for key in timestamp_keys if row.get(key) is not None), None)
        if is_at_or_before(timestamp, cutoff):
            filtered.append(row)
    return filtered
