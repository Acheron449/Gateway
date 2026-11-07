"""Owner-scoped risk series replayed from the paper portfolio's own records.

The Risk Dashboard used to read a mock dataset from an operator-only route.
This module derives the equity curve, drawdown path and current risk metrics
from what the paper portfolio already stores – the cash ledger and the
``Fill`` events – so the charts show the signed-in account's recorded history
rather than invented numbers.

Valuation basis: cash comes from the ledger's running total and each open
position is marked at its most recent fill price. The stored portfolio row
provides the current equity/cash figures and is appended as the final point.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.database import get_portfolio, get_portfolio_events, get_portfolio_history

CASH_LEDGER_LIMIT = 20000

SERIES_NOTE = (
    "Replayed from this paper portfolio's recorded cash flows and fills; "
    "open positions are marked at their last fill price."
)


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse a stored ISO timestamp, tolerating a trailing ``Z``."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile over an already sorted list."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _return_series(points: list[dict[str, Any]]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(points, points[1:]):
        base = previous["equity"]
        if base:
            returns.append((current["equity"] - base) / base)
    return returns


def build_equity_series(portfolio: dict[str, Any], ledger: list[dict[str, Any]],
                        events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild the account's equity path from ledger rows and fill events.

    Every ledger row moves cash; every ``Fill`` event moves a position and
    refreshes its mark. Both are merged on timestamp so a point exists after
    each change, and the stored portfolio state is appended last.
    """
    steps: list[tuple[datetime, str, dict[str, Any]]] = []

    for row in ledger:
        timestamp = _parse_timestamp(row.get("timestamp"))
        if timestamp is None:
            continue
        steps.append((timestamp, "cash", row))

    for event in events:
        if event.get("event_type") != "Fill":
            continue
        data = event.get("event_data")
        if not isinstance(data, dict):
            continue
        timestamp = _parse_timestamp(data.get("timestamp") or event.get("timestamp"))
        if timestamp is None:
            continue
        steps.append((timestamp, "fill", data))

    steps.sort(key=lambda step: (step[0], 0 if step[1] == "cash" else 1))

    cash = 0.0
    holdings: dict[str, dict[str, float]] = {}
    points: list[dict[str, Any]] = []

    for timestamp, kind, payload in steps:
        if kind == "cash":
            cash += float(payload.get("amount") or 0.0)
        else:
            instrument = str(payload.get("instrument_id") or "").upper()
            quantity = float(payload.get("qty") or 0.0)
            price = float(payload.get("price") or 0.0)
            side = str(payload.get("side") or "").lower()
            if not instrument or quantity <= 0:
                continue
            held = holdings.setdefault(instrument, {"quantity": 0.0, "price": 0.0})
            if side == "sell":
                held["quantity"] -= quantity
            else:
                held["quantity"] += quantity
            held["price"] = price
            if held["quantity"] <= 1e-9:
                holdings.pop(instrument, None)

        equity = cash + sum(held["quantity"] * held["price"] for held in holdings.values())
        points.append({
            "time": timestamp.isoformat(),
            "equity": _round(equity),
            "cash": _round(cash),
        })

    stored_equity = float(portfolio.get("equity") or 0.0)
    if not points:
        timestamp = _parse_timestamp(portfolio.get("updated_at")) or datetime.now(timezone.utc)
        points.append({
            "time": timestamp.isoformat(),
            "equity": _round(stored_equity),
            "cash": _round(float(portfolio.get("cash") or 0.0)),
        })
    else:
        last = points[-1]
        if abs(last["equity"] - stored_equity) >= 0.01:
            timestamp = _parse_timestamp(portfolio.get("updated_at")) or datetime.now(timezone.utc)
            points.append({
                "time": timestamp.isoformat(),
                "equity": _round(stored_equity),
                "cash": _round(float(portfolio.get("cash") or 0.0)),
            })

    return points


def drawdown_series(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Percent below the running peak for each equity point (zero or negative)."""
    peak = 0.0
    series: list[dict[str, Any]] = []
    for point in points:
        peak = max(peak, point["equity"])
        drawdown = ((point["equity"] - peak) / peak) * 100 if peak > 0 else 0.0
        series.append({"time": point["time"], "drawdown": _round(drawdown, 4)})
    return series


def _position_rows(portfolio: dict[str, Any], equity: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for position in portfolio.get("positions", []):
        quantity = float(position.get("quantity") or 0.0)
        if abs(quantity) <= 1e-9:
            continue
        market_value = float(position.get("market_value") or 0.0)
        rows.append({
            "instrument_id": str(position.get("instrument_id") or ""),
            "quantity": quantity,
            "avg_cost": _round(float(position.get("avg_cost") or 0.0), 4),
            "market_value": _round(market_value),
            "unrealized_pnl": _round(float(position.get("unrealized_pnl") or 0.0)),
            "realized_pnl": _round(float(position.get("realized_pnl") or 0.0)),
            "pct_of_equity": _round((abs(market_value) / equity) * 100 if equity > 0 else 0.0),
        })
    rows.sort(key=lambda row: abs(row["market_value"]), reverse=True)
    return rows


def build_portfolio_risk(portfolio_id: str) -> dict[str, Any]:
    """Assemble the Risk Dashboard payload from stored portfolio records."""
    portfolio = get_portfolio(portfolio_id) or {}
    ledger = get_portfolio_history(portfolio_id, CASH_LEDGER_LIMIT)
    events = get_portfolio_events(portfolio_id)

    points = build_equity_series(portfolio, ledger, events)
    drawdowns = drawdown_series(points)

    equity = float(portfolio.get("equity") or points[-1]["equity"])
    cash = float(portfolio.get("cash") or points[-1]["cash"])
    returns = _return_series(points)

    drawdown_values = [point["drawdown"] for point in drawdowns]
    worst_drawdown = abs(min(drawdown_values)) if drawdown_values else 0.0
    current_drawdown = abs(drawdown_values[-1]) if drawdown_values else 0.0

    # Daily P&L is measured from the last point before the current UTC day.
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    opening_equity = points[0]["equity"]
    for point in points:
        timestamp = _parse_timestamp(point["time"])
        if timestamp is not None and timestamp < start_of_day:
            opening_equity = point["equity"]
    daily_pnl = equity - opening_equity
    daily_pnl_pct = (daily_pnl / opening_equity) * 100 if opening_equity else 0.0

    first_equity = points[0]["equity"]
    total_return_pct = ((equity - first_equity) / first_equity) * 100 if first_equity else 0.0

    positions = _position_rows(portfolio, equity)
    gross_market_value = sum(abs(row["market_value"]) for row in positions)
    net_market_value = sum(row["market_value"] for row in positions)

    sorted_returns = sorted(returns)
    var_95_pct = abs(_percentile(sorted_returns, 0.05)) * 100
    var_99_pct = abs(_percentile(sorted_returns, 0.01)) * 100

    return {
        "portfolio_id": portfolio_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "equity": _round(equity),
        "cash": _round(cash),
        "buying_power": _round(float(portfolio.get("buying_power") or 0.0)),
        "daily_pnl": _round(daily_pnl),
        "daily_pnl_pct": _round(daily_pnl_pct),
        "total_return_pct": _round(total_return_pct),
        "max_drawdown": _round(worst_drawdown),
        "current_drawdown": _round(current_drawdown),
        "open_positions": len(positions),
        "gross_exposure": _round(gross_market_value / equity, 4) if equity > 0 else 0.0,
        "net_exposure": _round(net_market_value / equity, 4) if equity > 0 else 0.0,
        "var_95": _round(var_95_pct),
        "var_99": _round(var_99_pct),
        "var_95_amount": _round((var_95_pct / 100) * equity),
        "var_99_amount": _round((var_99_pct / 100) * equity),
        "concentration_risk": [
            {"symbol": row["instrument_id"], "pct": row["pct_of_equity"]}
            for row in positions
        ],
        "equity_curve": points,
        "drawdown_curve": drawdowns,
        "positions": positions,
        "series_note": SERIES_NOTE,
    }
