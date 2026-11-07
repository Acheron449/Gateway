"""Black-Scholes module (SRS §5.2, FR-O1..O6).

Covers all five §5.2 validation items: put-call parity, monotonicity and delta
bounds, the IV round trip, finite deep-OTM / near-expiry results, and greeks
against central finite differences. The round trip is asserted on σ wherever
the price is numerically sensitive to volatility and on the price itself where
it provably is not (deep in-the-money, one day to expiry).
"""

from __future__ import annotations

import asyncio
import math

import pytest
from fastapi import HTTPException

from app.api.v1 import quant
from app.auth import User
from app.services import quant_options as bs


def _user() -> User:
    return User(id="opt-alice", email="opt-alice@example.test", subject="opt-alice")


def _price(S=100.0, K=100.0, T=0.5, r=0.05, q=0.02, sigma=0.2, kind="call"):
    return bs.price(S=S, K=K, T=T, r=r, q=q, sigma=sigma, kind=kind)


def _value(**kwargs) -> float:
    return _price(**kwargs)["price"]


def _raw_vega(**kwargs) -> float:
    """Reported vega is per 1% of volatility; this is dV/dσ."""
    return _price(**kwargs)["greeks"]["vega"] * 100.0


# --- §5.2 validation 1: put-call parity ------------------------------------


@pytest.mark.parametrize(
    "S,K,T,r,q,sigma",
    [
        (100.0, 100.0, 1.0, 0.05, 0.0, 0.2),
        (100.0, 80.0, 0.25, 0.03, 0.01, 0.35),
        (50.0, 75.0, 2.0, 0.04, 0.02, 0.6),
        (150.0, 100.0, 1.0 / 365.0, 0.05, 0.0, 0.25),
        (100.0, 100.0, 3.0, 0.0, 0.0, 0.15),
    ],
)
def test_put_call_parity(S, K, T, r, q, sigma) -> None:
    call = _value(S=S, K=K, T=T, r=r, q=q, sigma=sigma, kind="call")
    put = _value(S=S, K=K, T=T, r=r, q=q, sigma=sigma, kind="put")
    expected = S * math.exp(-q * T) - K * math.exp(-r * T)
    assert call - put == pytest.approx(expected, abs=1e-8)


# --- §5.2 validation 2: monotonicity and delta bounds ----------------------


def test_call_value_increases_with_spot_and_volatility_and_falls_with_strike() -> None:
    spots = [60.0, 80.0, 100.0, 120.0, 140.0]
    calls = [_value(S=spot, K=100.0) for spot in spots]
    assert calls == sorted(calls) and len(set(calls)) == len(calls)

    sigmas = [0.05, 0.1, 0.2, 0.4, 0.8]
    by_vol = [_value(sigma=sigma) for sigma in sigmas]
    assert by_vol == sorted(by_vol) and len(set(by_vol)) == len(by_vol)

    strikes = [60.0, 80.0, 100.0, 120.0, 140.0]
    by_strike = [_value(K=strike) for strike in strikes]
    assert by_strike == sorted(by_strike, reverse=True)


def test_delta_bounds_and_gamma_vega_signs_across_the_strike_grid() -> None:
    for S in (50.0, 100.0, 150.0):
        for K in (50.0, 100.0, 150.0):
            for sigma in (0.05, 0.2, 1.0):
                call = _price(S=S, K=K, sigma=sigma, kind="call")["greeks"]
                put = _price(S=S, K=K, sigma=sigma, kind="put")["greeks"]
                assert 0.0 <= call["delta"] <= 1.0
                assert -1.0 <= put["delta"] <= 0.0
                assert call["gamma"] >= 0.0 and put["gamma"] >= 0.0
                assert call["vega"] >= 0.0 and put["vega"] >= 0.0
                assert call["vega"] == pytest.approx(put["vega"], rel=1e-12, abs=1e-12)


# --- §5.2 validation 3: implied-volatility round trip ----------------------

ROUND_TRIP = [
    (moneyness, T, sigma)
    for moneyness in (0.5, 0.75, 1.0, 1.25, 1.5)
    for T in (1.0 / 365.0, 0.25, 1.0, 3.0)
    for sigma in (0.05, 0.2, 0.5, 1.0, 2.0)
]


@pytest.mark.parametrize("kind", ["call", "put"])
def test_implied_volatility_round_trip(kind: str) -> None:
    for moneyness in (0.5, 0.75, 1.0, 1.25, 1.5):
        for T in (1.0 / 365.0, 0.25, 1.0, 3.0):
            for sigma in (0.05, 0.2, 0.5, 1.0, 2.0):
                S, K, r, q = 100.0 * moneyness, 100.0, 0.05, 0.01
                target = _value(S=S, K=K, T=T, r=r, q=q, sigma=sigma, kind=kind)
                solved = bs.implied_volatility(
                    market_price=target, S=S, K=K, T=T, r=r, q=q, kind=kind
                )
                assert solved["converged"] is True, (moneyness, T, sigma, kind)
                assert solved["iterations"] <= bs.MAX_ITERATIONS
                # §5.2 allows 1e-8 on σ or 1e-6 on price; the price is the
                # only guarantee where dV/dσ is below numerical resolution.
                assert solved["model_price"] == pytest.approx(target, abs=1e-6)
                # σ is only recoverable where the price responds to it.
                if _raw_vega(S=S, K=K, T=T, r=r, q=q, sigma=sigma, kind=kind) >= 0.01:
                    assert solved["implied_volatility"] == pytest.approx(sigma, abs=1e-6)
                else:
                    assert solved["price_error"] == pytest.approx(0.0, abs=1e-6)


def test_implied_volatility_is_flat_but_price_exact_when_deep_in_the_money() -> None:
    """Documents the conditioning limit instead of pretending σ is recoverable."""
    kwargs = dict(S=150.0, K=100.0, T=1.0 / 365.0, r=0.05, q=0.01)
    target = _value(**kwargs, sigma=0.05)
    solved = bs.implied_volatility(market_price=target, **kwargs)  # type: ignore[arg-type]
    assert solved["converged"] is True
    assert solved["model_price"] == pytest.approx(target, abs=1e-6)
    assert _raw_vega(**kwargs, sigma=0.05) < 0.01


# --- §5.2 validation 4: deep OTM and near expiry stay finite ---------------


@pytest.mark.parametrize(
    "S,K,T,sigma",
    [
        (100.0, 200.0, 1.0 / 365.0, 0.2),
        (100.0, 500.0, 0.01, 0.05),
        (100.0, 100.0, 1e-8, 0.2),
        (400.0, 100.0, 1.0 / 365.0, 0.2),
        (1.0, 100.0, 3.0, 2.0),
    ],
)
def test_extreme_options_return_finite_non_negative_values(S, K, T, sigma) -> None:
    for kind in ("call", "put"):
        result = _price(S=S, K=K, T=T, sigma=sigma, kind=kind)
        assert math.isfinite(result["price"]) and result["price"] >= 0.0
        assert result["price"] <= result["bounds"]["upper"] + 1e-8
        for greek in result["greeks"].values():
            assert math.isfinite(greek)
        assert math.isfinite(result["time_value"]) or result["time_value"] == 0.0
    assert _price(S=100.0, K=200.0, T=1.0 / 365.0)["price"] == 0.0
    assert _price(S=100.0, K=100.0, T=0.5 / 365.0)["near_expiry_unstable"] is True


def test_zero_volatility_is_the_discounted_intrinsic() -> None:
    result = _price(S=100.0, K=90.0, T=1.0, r=0.05, q=0.0, sigma=0.0, kind="call")
    assert result["price"] == pytest.approx(100.0 - 90.0 * math.exp(-0.05), abs=1e-10)
    assert result["d1"] is None and result["d2"] is None
    assert result["greeks"]["delta"] == 1.0
    assert result["greeks"]["gamma"] == 0.0 and result["greeks"]["vega"] == 0.0
    out_of_the_money = _price(S=90.0, K=100.0, sigma=0.0, kind="call")
    assert out_of_the_money["price"] == 0.0
    assert out_of_the_money["greeks"]["delta"] == 0.0


# --- §5.2 validation 5: greeks match central finite differences ------------


@pytest.mark.parametrize("kind", ["call", "put"])
def test_greeks_match_central_finite_differences(kind: str) -> None:
    base = dict(S=100.0, K=105.0, T=0.5, r=0.05, q=0.02, sigma=0.25)
    greeks = _price(**base, kind=kind)["greeks"]
    spot, vol, rate = base["S"], base["sigma"], base["r"]
    T = base["T"]

    def value(**overrides) -> float:
        return _value(**{**base, **overrides}, kind=kind)

    h_spot = 0.01
    delta_fd = (value(S=spot + h_spot) - value(S=spot - h_spot)) / (2 * h_spot)
    gamma_fd = (
        value(S=spot + h_spot) - 2 * value(S=spot) + value(S=spot - h_spot)
    ) / (h_spot * h_spot)

    h_vol = 1e-5
    vega_fd = (value(sigma=vol + h_vol) - value(sigma=vol - h_vol)) / (2 * h_vol) * 0.01

    h_time = 1e-5
    theta_fd = -(value(T=T + h_time) - value(T=T - h_time)) / (2 * h_time) / 365.0

    h_rate = 1e-5
    rho_fd = (value(r=rate + h_rate) - value(r=rate - h_rate)) / (2 * h_rate) * 0.01

    assert greeks["delta"] == pytest.approx(delta_fd, rel=1e-4, abs=1e-10)
    assert greeks["gamma"] == pytest.approx(gamma_fd, rel=1e-4, abs=1e-10)
    assert greeks["vega"] == pytest.approx(vega_fd, rel=1e-4, abs=1e-12)
    assert greeks["theta"] == pytest.approx(theta_fd, rel=1e-4, abs=1e-12)
    assert greeks["rho"] == pytest.approx(rho_fd, rel=1e-4, abs=1e-12)


# --- FR-O3 / FR-O4 ---------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,field",
    [
        ({"S": 0.0}, "S"),
        ({"S": -5.0}, "S"),
        ({"K": 0.0}, "K"),
        ({"K": -1.0}, "K"),
        ({"T": 0.0}, "T"),
        ({"T": -0.25}, "T"),
        ({"sigma": -0.01}, "sigma"),
        ({"sigma": float("nan")}, "sigma"),
        ({"r": float("inf")}, "r"),
        ({"kind": "straddle"}, "type"),
    ],
)
def test_invalid_inputs_name_the_offending_field(overrides, field) -> None:
    with pytest.raises(bs.OptionInputError) as excinfo:
        _price(**overrides)
    assert excinfo.value.field == field


def test_every_response_states_the_model_boundaries() -> None:
    priced = _price()
    solved = bs.implied_volatility(market_price=priced["price"], S=100.0, K=100.0, T=0.5, r=0.05, q=0.02)
    for result in (priced, solved):
        assert len(result["model_boundaries"]) == 5
        assert "European exercise only" in result["model_boundaries"][0]
        assert result["engine_version"] == bs.ENGINE_VERSION
    assert "skew" in " ".join(priced["model_boundaries"])


def test_implied_volatility_refuses_prices_outside_the_band() -> None:
    with pytest.raises(bs.ImpliedVolBoundError) as below:
        bs.implied_volatility(market_price=1.0, S=100.0, K=50.0, T=1.0, r=0.05)
    assert below.value.code == "price_below_intrinsic"
    assert below.value.bound == pytest.approx(100.0 - 50.0 * math.exp(-0.05), abs=1e-8)

    with pytest.raises(bs.ImpliedVolBoundError) as above:
        bs.implied_volatility(market_price=101.0, S=100.0, K=100.0, T=1.0, r=0.05)
    assert above.value.code == "price_above_upper_bound"
    assert above.value.bound == pytest.approx(100.0, abs=1e-8)

    with pytest.raises(bs.ImpliedVolBoundError) as put_above:
        bs.implied_volatility(market_price=120.0, S=100.0, K=100.0, T=1.0, r=0.05, kind="put")
    assert put_above.value.code == "price_above_upper_bound"
    assert put_above.value.bound == pytest.approx(100.0 * math.exp(-0.05), abs=1e-8)


def test_implied_volatility_reports_boundary_outcomes() -> None:
    intrinsic_price = 100.0 - 50.0 * math.exp(-0.05)
    at_intrinsic = bs.implied_volatility(market_price=intrinsic_price, S=100.0, K=50.0, T=1.0, r=0.05)
    assert at_intrinsic["implied_volatility"] == 0.0
    assert at_intrinsic["converged"] is True and at_intrinsic["solver"] == "boundary"

    at_ceiling = bs.implied_volatility(market_price=100.0, S=100.0, K=100.0, T=1.0, r=0.0)
    assert at_ceiling["converged"] is False
    assert at_ceiling["implied_volatility"] == bs.MAX_SIGMA
    assert at_ceiling["warnings"]


# --- API -------------------------------------------------------------------


def _price_request(**overrides) -> quant.OptionPriceRequest:
    base = dict(S=100.0, K=100.0, T=0.5, r=0.05, q=0.02, sigma=0.2, type="call")
    return quant.OptionPriceRequest(**{**base, **overrides})


def test_price_route_returns_value_greeks_and_boundaries() -> None:
    response = asyncio.run(quant.options_price(_price_request(), _user()))
    assert response["type"] == "call"
    assert response["price"] > 0
    assert set(response["greeks"]) == {"delta", "gamma", "vega", "theta", "rho"}
    assert response["greek_units"]["theta"].startswith("currency per calendar day")
    assert len(response["model_boundaries"]) == 5


def test_price_route_maps_bad_input_to_400_with_the_field_named() -> None:
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(quant.options_price(_price_request(T=0.0), _user()))
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["field"] == "T"
    assert "T" in excinfo.value.detail["message"]

    with pytest.raises(HTTPException) as bad_type:
        asyncio.run(quant.options_price(_price_request(type="straddle"), _user()))
    assert bad_type.value.status_code == 400
    assert bad_type.value.detail["field"] == "type"


def test_implied_vol_route_solves_and_maps_bounds_to_422() -> None:
    priced = asyncio.run(quant.options_price(_price_request(), _user()))
    request = quant.OptionImpliedVolRequest(
        market_price=priced["price"], S=100.0, K=100.0, T=0.5, r=0.05, q=0.02, type="call"
    )
    solved = asyncio.run(quant.options_implied_vol(request, _user()))
    assert solved["converged"] is True
    assert solved["implied_volatility"] == pytest.approx(0.2, abs=1e-6)
    assert solved["solver"] in {"brent", "bisection"}

    with pytest.raises(HTTPException) as below:
        asyncio.run(
            quant.options_implied_vol(
                quant.OptionImpliedVolRequest(
                    market_price=0.5, S=100.0, K=50.0, T=1.0, r=0.05, type="call"
                ),
                _user(),
            )
        )
    assert below.value.status_code == 422
    assert below.value.detail["code"] == "price_below_intrinsic"
    assert below.value.detail["bound"] > 0

    with pytest.raises(HTTPException) as invalid:
        asyncio.run(
            quant.options_implied_vol(
                quant.OptionImpliedVolRequest(
                    market_price=10.0, S=100.0, K=100.0, T=0.0, r=0.05, type="call"
                ),
                _user(),
            )
        )
    assert invalid.value.status_code == 400
    assert invalid.value.detail["field"] == "T"
