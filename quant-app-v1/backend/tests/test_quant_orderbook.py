"""Simulated order book (SRS §5.3, FR-L1..L6).

Covers all five §5.3 validation items: seed determinism, size conservation
through aggregation, the market-maker inventory effect, a never-crossed ladder
and the FR-L6 output bounds under adversarial inputs.
"""

from __future__ import annotations

import asyncio
import math
import time

import pytest
from fastapi import HTTPException

from app.api.v1 import quant
from app.auth import User
from app.services import quant_orderbook as ob


def _user() -> User:
    return User(id="ob-alice", email="ob-alice@example.test", subject="ob-alice")


def _book(**overrides):
    base = dict(mid=191.42, seed=7, recent_return=0.004, lookback_return=0.012)
    return ob.simulate(**{**base, **overrides})


# --- §5.3 validation 1: determinism ---------------------------------------


def test_same_seed_and_inputs_produce_an_identical_ladder() -> None:
    first = _book()
    second = _book()
    assert first == second
    assert first["output_hash"] == second["output_hash"]
    assert first["simulated"] is True
    assert first["label"] == ob.LABEL


def test_a_different_seed_produces_a_different_ladder() -> None:
    assert _book(seed=8)["output_hash"] != _book(seed=7)["output_hash"]


# --- §5.3 validation 2: conservation --------------------------------------


def test_no_size_is_invented_or_lost_by_aggregation() -> None:
    book = _book(agents=300)
    visible = sum(level["size"] for level in book["levels"])
    assert visible == pytest.approx(book["visible_size"], abs=1e-6)
    assert book["visible_size"] + book["dropped_size"] == pytest.approx(
        book["total_size"], abs=1e-6
    )
    assert book["conservation_delta"] == pytest.approx(0.0, abs=1e-6)
    assert sum(book["size_by_archetype"].values()) == pytest.approx(book["total_size"], abs=1e-4)
    for level in book["levels"]:
        assert sum(segment["size"] for segment in level["contributions"]) == pytest.approx(
            level["size"], abs=1e-6
        )
        assert sum(segment["agents"] for segment in level["contributions"]) > 0


def test_truncated_levels_account_for_their_size() -> None:
    book = _book(agents=4_000, tick=0.0001, band=0.2)
    assert book["levels_truncated"]["bid"] > 0 or book["levels_truncated"]["ask"] > 0
    assert book["dropped_size"] > 0
    assert book["visible_size"] + book["dropped_size"] == pytest.approx(
        book["total_size"], abs=1e-6
    )


# --- §5.3 validation 3: market-maker inventory ----------------------------


def test_market_maker_share_falls_as_inventory_grows_in_magnitude() -> None:
    shares = []
    for inventory in (0.0, 2.0, 10.0):
        book = _book(inventory=inventory)
        shares.append(book["size_by_archetype"]["market_maker"] / book["total_size"])
    assert shares[0] > shares[1] > shares[2]


def test_inventory_skews_the_market_maker_away_from_the_side_it_already_holds() -> None:
    # A larger population keeps the flat-book side split from being noise.
    long_book = _book(agents=5_000, inventory=10.0)
    flat_book = _book(agents=5_000, inventory=0.0)

    def market_maker_size(book, side):
        return sum(
            segment["size"]
            for level in book["levels"]
            if level["side"] == side
            for segment in level["contributions"]
            if segment["archetype"] == "market_maker"
        )

    assert market_maker_size(long_book, "ask") > market_maker_size(long_book, "bid")
    assert market_maker_size(flat_book, "ask") == pytest.approx(
        market_maker_size(flat_book, "bid"), rel=0.15
    )


# --- §5.3 validation 4: never crossed -------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"tick": 0.0001},
        {"spread_base": 1e-6, "spread_cv": 0.0},
        {"band": 0.4, "large_distance": 0.4},
        {"tick": 1.0},
        {"weights": {"market_maker": 1.0}},
        {"weights": {"momentum": 1.0}, "recent_return": 0.01},
        {"agents": 5_000, "tick": 0.001, "inventory": 25.0},
    ],
)
def test_the_ladder_is_never_crossed(overrides) -> None:
    book = _book(**overrides)
    bids = [level["price"] for level in book["levels"] if level["side"] == "bid"]
    asks = [level["price"] for level in book["levels"] if level["side"] == "ask"]
    assert all(price < book["mid"] for price in bids)
    assert all(price > book["mid"] for price in asks)
    assert book["crossed"] is False
    if book["best_bid"] is not None and book["best_ask"] is not None:
        assert book["best_bid"] < book["best_ask"]


# --- §5.3 validation 5 / FR-L6: bounds ------------------------------------


def test_levels_and_segments_are_bounded_for_adversarial_inputs() -> None:
    book = _book(agents=ob.MAX_AGENTS, tick=0.0001, band=0.5, large_distance=0.5)
    assert book["levels_per_side"]["bid"] <= ob.MAX_LEVELS_PER_SIDE
    assert book["levels_per_side"]["ask"] <= ob.MAX_LEVELS_PER_SIDE
    assert len(book["levels"]) <= 2 * ob.MAX_LEVELS_PER_SIDE
    for level in book["levels"]:
        assert len(level["contributions"]) <= ob.MAX_SEGMENTS
        assert level["size"] > 0
        assert 0.0 < level["share_of_side"] <= 1.0
    assert book["agents"] == ob.MAX_AGENTS


def test_default_simulation_is_inside_the_one_second_budget() -> None:
    started = time.perf_counter()
    book = ob.simulate(mid=191.42, seed=7)
    elapsed = time.perf_counter() - started
    assert book["agents"] == ob.DEFAULT_AGENTS
    assert elapsed < 1.0


def test_default_weights_and_contributions_match_the_archetype_table() -> None:
    book = _book(agents=1_000)
    assert book["weights"] == pytest.approx(ob.DEFAULT_WEIGHTS)
    assert set(book["size_by_archetype"]) == set(ob.ARCHETYPES)
    assert all(value > 0 for value in book["size_by_archetype"].values())
    seen = {
        segment["archetype"] for level in book["levels"] for segment in level["contributions"]
    }
    assert seen == set(ob.ARCHETYPES)


def test_weights_are_normalised_and_zero_weight_archetypes_contribute_nothing() -> None:
    book = _book(weights={"market_maker": 2.0, "noise": 2.0, "momentum": 0.0, "large_passive": 0.0})
    assert book["weights"]["market_maker"] == pytest.approx(0.5)
    assert book["size_by_archetype"]["momentum"] == 0.0
    assert book["size_by_archetype"]["large_passive"] == 0.0
    assert sum(book["weights"].values()) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"mid": 0.0}, "mid"),
        ({"mid": -1.0}, "mid"),
        ({"agents": 5}, "agents"),
        ({"agents": ob.MAX_AGENTS + 1}, "agents"),
        ({"seed": -1}, "seed"),
        ({"recent_return": -1.5}, "recent_return"),
        ({"lookback_volatility": 0.0}, "lookback_volatility"),
        ({"inventory": 100.0}, "inventory"),
        ({"spread_base": -0.001}, "spread_base"),
        ({"spread_cv": -0.001}, "spread_cv"),
        ({"band": 0.0}, "band"),
        ({"band": 0.9}, "band"),
        ({"inventory_penalty": -1.0}, "inventory_penalty"),
        ({"tick": 0.0}, "tick"),
        ({"tick": 500.0}, "tick"),
        ({"size_scale": 0.0}, "size_scale"),
        ({"large_distance": 0.001}, "large_distance"),
        ({"weights": {"whale": 1.0}}, "weights"),
        ({"weights": {"market_maker": -1.0, "noise": 2.0}}, "weights"),
        ({"weights": {"market_maker": 0.0, "noise": 0.0, "momentum": 0.0, "large_passive": 0.0}}, "weights"),
    ],
)
def test_invalid_inputs_name_the_offending_field(overrides, field) -> None:
    with pytest.raises(ob.OrderBookInputError) as excinfo:
        _book(**overrides)
    assert excinfo.value.field == field


def test_prices_snap_to_the_tick_grid_on_both_sides() -> None:
    book = _book(tick=0.05)
    for level in book["levels"]:
        assert level["price"] / 0.05 == pytest.approx(round(level["price"] / 0.05), abs=1e-6)


# --- API -------------------------------------------------------------------


def _request(**overrides) -> quant.OrderBookRequest:
    base = dict(mid=191.42, seed=7, agents=500, recent_return=0.004)
    return quant.OrderBookRequest(**{**base, **overrides})


def test_route_returns_the_label_ladder_and_parameters() -> None:
    response = asyncio.run(quant.orderbook_simulate(_request(), _user()))
    assert response["simulated"] is True
    assert "not exchange data" in response["label"]
    assert response["levels"] and response["best_bid"] < response["mid"] < response["best_ask"]
    assert response["engine_version"] == ob.ENGINE_VERSION
    assert response["parameters"]["spread_base"] == ob.DEFAULT_SPREAD_BASE
    assert response["seed"] == 7


def test_route_maps_bad_input_to_400_with_the_field_named() -> None:
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(quant.orderbook_simulate(_request(mid=0.0), _user()))
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["field"] == "mid"

    with pytest.raises(HTTPException) as tick:
        asyncio.run(quant.orderbook_simulate(_request(tick=0.0), _user()))
    assert tick.value.status_code == 400
    assert tick.value.detail["field"] == "tick"


def test_route_is_deterministic_end_to_end() -> None:
    first = asyncio.run(quant.orderbook_simulate(_request(), _user()))
    second = asyncio.run(quant.orderbook_simulate(_request(), _user()))
    assert first["output_hash"] == second["output_hash"]
    assert first["levels"] == second["levels"]
