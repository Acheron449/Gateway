"""Simulated order book (SRS §5.3, FR-L1..L6).

A population of agents drawn from four archetypes quotes around a mid price;
their quotes are snapped to a tick grid, aggregated into price bins and
attributed back to the archetype that placed them. The result is a model
output, never exchange data.

Every level holds the sizes contributed by each archetype, so a level can be
expanded to show *who* plausibly stands behind it.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Optional

import numpy as np

ENGINE_VERSION = "ob-1.0.0"
LABEL = "Simulated liquidity — not exchange data"
ARCHETYPES = ("market_maker", "momentum", "noise", "large_passive")
DEFAULT_WEIGHTS = {
    "market_maker": 0.40,
    "momentum": 0.20,
    "noise": 0.30,
    "large_passive": 0.10,
}
DEFAULT_AGENTS = 500
MIN_AGENTS = 10
MAX_AGENTS = 5_000
MAX_LEVELS_PER_SIDE = 200
MAX_SEGMENTS = 50
DEFAULT_TICK = 0.01
DEFAULT_SPREAD_BASE = 0.0004
DEFAULT_SPREAD_CV = 0.0001
DEFAULT_BAND = 0.005
DEFAULT_INVENTORY_PENALTY = 0.15
DEFAULT_LARGE_DISTANCE = 0.005
DEFAULT_SIZE_SCALE = 1_000.0
MAX_ABS_INVENTORY = 50.0


class OrderBookInputError(ValueError):
    """A bad input, with the offending field named."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise OrderBookInputError(field, f"{field} must be a finite number")
    return float(value)


def _normalise_weights(weights: Optional[dict[str, float]]) -> dict[str, float]:
    if weights is None:
        return dict(DEFAULT_WEIGHTS)
    if not isinstance(weights, dict):
        raise OrderBookInputError("weights", "weights must be an object keyed by archetype")
    unknown = set(weights) - set(ARCHETYPES)
    if unknown:
        raise OrderBookInputError(
            "weights", f"unknown archetype(s): {', '.join(sorted(unknown))}"
        )
    merged = {archetype: float(weights.get(archetype, 0.0)) for archetype in ARCHETYPES}
    total = 0.0
    for archetype, value in merged.items():
        if not math.isfinite(value) or value < 0:
            raise OrderBookInputError(
                "weights", f"weight for {archetype} must be a finite number of at least 0"
            )
        total += value
    if total <= 0:
        raise OrderBookInputError("weights", "at least one archetype weight must be positive")
    return {archetype: value / total for archetype, value in merged.items()}


def _validate(
    *,
    mid: float,
    agents: int,
    seed: int,
    recent_return: float,
    lookback_return: float,
    lookback_volatility: float,
    inventory: float,
    spread_base: float,
    spread_cv: float,
    band: float,
    inventory_penalty: float,
    tick: float,
    size_scale: float,
    large_distance: float,
) -> None:
    if not math.isfinite(mid) or mid <= 0:
        raise OrderBookInputError("mid", "mid must be a positive finite price")
    if isinstance(agents, bool) or not isinstance(agents, int) or not MIN_AGENTS <= agents <= MAX_AGENTS:
        raise OrderBookInputError(
            "agents", f"agents must be an integer between {MIN_AGENTS} and {MAX_AGENTS}"
        )
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
        raise OrderBookInputError("seed", "seed must be an integer between 0 and 2^63 - 1")
    if not math.isfinite(recent_return) or recent_return <= -1:
        raise OrderBookInputError("recent_return", "recent_return must be greater than -1")
    if not math.isfinite(lookback_return) or lookback_return <= -1:
        raise OrderBookInputError("lookback_return", "lookback_return must be greater than -1")
    if not math.isfinite(lookback_volatility) or lookback_volatility <= 0:
        raise OrderBookInputError(
            "lookback_volatility", "lookback_volatility must be a positive finite number"
        )
    if not math.isfinite(inventory) or abs(inventory) > MAX_ABS_INVENTORY:
        raise OrderBookInputError(
            "inventory", f"inventory must be a finite number within ±{MAX_ABS_INVENTORY:g}"
        )
    if not math.isfinite(spread_base) or spread_base < 0:
        raise OrderBookInputError("spread_base", "spread_base must be at least 0")
    if not math.isfinite(spread_cv) or spread_cv < 0:
        raise OrderBookInputError("spread_cv", "spread_cv must be at least 0")
    if not math.isfinite(band) or not 0 < band <= 0.5:
        raise OrderBookInputError("band", "band must be greater than 0 and at most 0.5")
    if not math.isfinite(inventory_penalty) or inventory_penalty < 0:
        raise OrderBookInputError("inventory_penalty", "inventory_penalty must be at least 0")
    if not math.isfinite(tick) or tick <= 0 or tick > mid:
        raise OrderBookInputError("tick", "tick must be greater than 0 and no larger than mid")
    if not math.isfinite(size_scale) or size_scale <= 0:
        raise OrderBookInputError("size_scale", "size_scale must be greater than 0")
    if not math.isfinite(large_distance) or not 0.005 <= large_distance <= 0.5:
        raise OrderBookInputError(
            "large_distance", "large_distance must be between 0.005 and 0.5 (fraction of mid)"
        )


def _snap(mid: float, side: str, offset: float, tick: float) -> float:
    """Snap to the tick grid on the correct side, so bids stay below mid."""
    offset = max(offset, tick)
    if side == "bid":
        price = math.floor((mid - offset) / tick + 1e-12) * tick
        if price >= mid:
            price = mid - tick
    else:
        price = math.ceil((mid + offset) / tick - 1e-12) * tick
        if price <= mid:
            price = mid + tick
    return round(price, 10)


def _quote(
    archetype: str,
    rng: np.random.Generator,
    *,
    mid: float,
    recent_return: float,
    momentum_z: float,
    inventory: float,
    spread_base: float,
    spread_cv: float,
    band: float,
    inventory_penalty: float,
    size_scale: float,
    large_distance: float,
) -> Optional[tuple[str, float, float]]:
    """Return ``(side, offset_from_mid, size)`` for one agent, or None."""
    if archetype == "market_maker":
        # Inventory is skewed against: a long book quotes less and on the ask.
        skew = max(-1.0, min(1.0, inventory_penalty * inventory))
        bid_probability = 0.5 - 0.4 * skew
        side = "bid" if rng.random() < bid_probability else "ask"
        half_spread = abs(float(rng.normal(spread_base, spread_cv)))
        size = (
            size_scale
            * float(rng.lognormal(0.0, 0.8))
            / (1.0 + inventory_penalty * abs(inventory))
        )
        return side, mid * half_spread, size

    if archetype == "momentum":
        strength = min(abs(momentum_z), 3.0)
        if strength <= 0.0 or recent_return == 0.0:
            return None
        side = "bid" if recent_return > 0 else "ask"
        size = size_scale * strength * float(rng.uniform(0.5, 1.5))
        return side, mid * float(rng.uniform(0.0, band * 0.5)), size

    if archetype == "noise":
        side = "bid" if rng.random() < 0.5 else "ask"
        size = size_scale * 0.5 * float(rng.lognormal(0.0, 1.0))
        return side, mid * float(rng.uniform(0.0, band)), size

    # large passive: block liquidity, never inside the minimum distance.
    side = "bid" if rng.random() < 0.5 else "ask"
    distance = float(rng.uniform(large_distance, min(0.5, large_distance * 4.0)))
    size = size_scale * 5.0 * float(rng.lognormal(0.0, 0.5))
    return side, mid * distance, size


def _output_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def simulate(
    *,
    mid: float,
    seed: int = 7,
    agents: int = DEFAULT_AGENTS,
    weights: Optional[dict[str, float]] = None,
    recent_return: float = 0.0,
    lookback_return: Optional[float] = None,
    lookback_volatility: Optional[float] = None,
    inventory: float = 0.0,
    spread_base: float = DEFAULT_SPREAD_BASE,
    spread_cv: float = DEFAULT_SPREAD_CV,
    band: float = DEFAULT_BAND,
    inventory_penalty: float = DEFAULT_INVENTORY_PENALTY,
    tick: float = DEFAULT_TICK,
    size_scale: float = DEFAULT_SIZE_SCALE,
    large_distance: float = DEFAULT_LARGE_DISTANCE,
) -> dict[str, Any]:
    """One seeded snapshot of the simulated ladder (FR-L1, FR-L5)."""
    resolved_weights = _normalise_weights(weights)
    lookback = recent_return if lookback_return is None else float(lookback_return)
    if lookback_volatility is None:
        reference = lookback if lookback != 0.0 else (recent_return if recent_return != 0.0 else 0.01)
        volatility = abs(reference)
    else:
        volatility = float(lookback_volatility)
    _validate(
        mid=float(mid),
        agents=agents,
        seed=seed,
        recent_return=float(recent_return),
        lookback_return=lookback,
        lookback_volatility=volatility,
        inventory=float(inventory),
        spread_base=float(spread_base),
        spread_cv=float(spread_cv),
        band=float(band),
        inventory_penalty=float(inventory_penalty),
        tick=float(tick),
        size_scale=float(size_scale),
        large_distance=float(large_distance),
    )

    rng = np.random.Generator(np.random.PCG64(seed))
    momentum_z = lookback / volatility
    population = rng.choice(
        len(ARCHETYPES), size=agents, p=[resolved_weights[archetype] for archetype in ARCHETYPES]
    )

    bins: dict[tuple[str, float], dict[str, float]] = {}
    counts: dict[tuple[str, float], dict[str, int]] = {}
    emitted_by_archetype = {archetype: 0.0 for archetype in ARCHETYPES}
    emitted_total = 0.0

    for index in population:
        archetype = ARCHETYPES[int(index)]
        quote = _quote(
            archetype,
            rng,
            mid=float(mid),
            recent_return=float(recent_return),
            momentum_z=momentum_z,
            inventory=float(inventory),
            spread_base=float(spread_base),
            spread_cv=float(spread_cv),
            band=float(band),
            inventory_penalty=float(inventory_penalty),
            size_scale=float(size_scale),
            large_distance=float(large_distance),
        )
        if quote is None:
            continue
        side, offset, size = quote
        if not math.isfinite(size) or size <= 0:
            continue
        price = _snap(float(mid), side, offset, float(tick))
        key = (side, price)
        contributions = bins.setdefault(key, {})
        contributions[archetype] = contributions.get(archetype, 0.0) + size
        agent_counts = counts.setdefault(key, {})
        agent_counts[archetype] = agent_counts.get(archetype, 0) + 1
        emitted_by_archetype[archetype] += size
        emitted_total += size

    bids = sorted((key for key in bins if key[0] == "bid"), key=lambda key: key[1], reverse=True)
    asks = sorted((key for key in bins if key[0] == "ask"), key=lambda key: key[1])
    kept = {"bid": bids[:MAX_LEVELS_PER_SIDE], "ask": asks[:MAX_LEVELS_PER_SIDE]}
    dropped = {
        "bid": bids[MAX_LEVELS_PER_SIDE:],
        "ask": asks[MAX_LEVELS_PER_SIDE:],
    }
    dropped_size = sum(
        sum(bins[key].values()) for side, keys in dropped.items() for key in keys
    )

    levels: list[dict[str, Any]] = []
    visible_size = 0.0
    for side in ("bid", "ask"):
        side_size = sum(sum(bins[key].values()) for key in kept[side])
        for key in kept[side]:
            contributions = bins[key]
            size = sum(contributions.values())
            visible_size += size
            segments = [
                {
                    "archetype": archetype,
                    "size": round(contributions[archetype], 9),
                    "share": round(contributions[archetype] / size, 6),
                    "agents": counts[key].get(archetype, 0),
                }
                for archetype in ARCHETYPES
                if contributions.get(archetype, 0.0) > 0
            ][:MAX_SEGMENTS]
            levels.append(
                {
                    "price": key[1],
                    "side": side,
                    "size": round(size, 9),
                    "share_of_side": round(size / side_size, 6) if side_size else 0.0,
                    "contributions": segments,
                }
            )

    best_bid = kept["bid"][0][1] if kept["bid"] else None
    best_ask = kept["ask"][0][1] if kept["ask"] else None
    crossed = bool(best_bid is not None and best_ask is not None and best_bid >= best_ask)

    payload: dict[str, Any] = {
        "simulated": True,
        "label": LABEL,
        "engine_version": ENGINE_VERSION,
        "mid": round(float(mid), 10),
        "seed": seed,
        "agents": agents,
        "levels": levels,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "crossed": crossed,
        "spread": round(best_ask - best_bid, 10) if best_bid is not None and best_ask is not None else None,
        "spread_ticks": (
            round((best_ask - best_bid) / float(tick), 6)
            if best_bid is not None and best_ask is not None
            else None
        ),
        "levels_per_side": {"bid": len(kept["bid"]), "ask": len(kept["ask"])},
        "levels_truncated": {"bid": len(dropped["bid"]), "ask": len(dropped["ask"])},
        "total_size": round(emitted_total, 6),
        "visible_size": round(visible_size, 6),
        "dropped_size": round(dropped_size, 6),
        "conservation_delta": round(emitted_total - visible_size - dropped_size, 9),
        "size_by_archetype": {
            archetype: round(value, 6) for archetype, value in emitted_by_archetype.items()
        },
        "weights": resolved_weights,
        "parameters": {
            "spread_base": float(spread_base),
            "spread_cv": float(spread_cv),
            "band": float(band),
            "inventory_penalty": float(inventory_penalty),
            "inventory": float(inventory),
            "tick": float(tick),
            "size_scale": float(size_scale),
            "large_distance": float(large_distance),
            "recent_return": float(recent_return),
            "lookback_return": lookback,
            "lookback_volatility": volatility,
        },
        "disclaimer": (
            "Simulated liquidity — not exchange data. Agent quotes from a seeded model; "
            "no order book or trade feed is used."
        ),
    }
    payload["output_hash"] = _output_hash(
        {key: value for key, value in payload.items() if key != "output_hash"}
    )
    return payload
