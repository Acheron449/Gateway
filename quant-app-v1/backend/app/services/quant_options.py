"""Black-Scholes pricing and implied volatility (SRS §5.2, FR-O1..O6).

European options on a continuous dividend yield ``q``. Every response carries
the model boundaries of FR-O4, and the implied-volatility solver reports its
own convergence status rather than pretending every price has an answer.

Reporting conventions (SRS §5.2): theta per calendar day, vega and rho per 1
percentage point of volatility / rate.
"""

from __future__ import annotations

import math
from typing import Any, Literal

ENGINE_VERSION = "bs-1.0.0"
KINDS = ("call", "put")
MIN_SIGMA = 1e-4
MAX_SIGMA = 5.0
SIGMA_TOL = 1e-8
PRICE_TOL = 1e-12
# Prices are returned rounded to 10 dp, so the no-arbitrage guard allows that
# much representation noise — it never clamps a meaningful violation.
BOUND_TOL = 1e-8
MAX_ITERATIONS = 200
NEAR_EXPIRY_YEARS = 1.0 / 365.0

MODEL_BOUNDARIES = (
    "European exercise only: no early exercise and no American premium.",
    "Continuous dividend yield q, not discrete dividends.",
    "Constant volatility: no skew or smile.",
    "Constant risk-free rate r.",
    "Frictionless, continuous trading: no credit, funding or margin effects.",
)

GREEK_UNITS = {
    "delta": "per 1.0 change in the underlying price",
    "gamma": "change in delta per 1.0 change in the underlying price",
    "vega": "currency per 1 volatility point (dV/dσ ÷ 100)",
    "theta": "currency per calendar day (dV/dt ÷ 365)",
    "rho": "currency per 1 rate point (dV/dr ÷ 100)",
}

SQRT_2 = math.sqrt(2.0)
SQRT_2PI = math.sqrt(2.0 * math.pi)


class OptionInputError(ValueError):
    """A bad input, with the offending field named (FR-O3)."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class ImpliedVolBoundError(ValueError):
    """A market price outside the no-arbitrage band for this option."""

    def __init__(self, code: str, message: str, *, bound: float) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.bound = bound
        self.field = "market_price"


def _norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x / SQRT_2)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _validate_inputs(S: float, K: float, T: float, r: float, q: float) -> None:
    for field, value in (("S", S), ("K", K), ("T", T), ("r", r), ("q", q)):
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise OptionInputError(field, f"{field} must be a finite number")
    if S <= 0:
        raise OptionInputError("S", "S must be greater than 0")
    if K <= 0:
        raise OptionInputError("K", "K must be greater than 0")
    if T <= 0:
        raise OptionInputError("T", "T must be greater than 0 (years to expiry)")


def _validate_kind(kind: str) -> None:
    if kind not in KINDS:
        raise OptionInputError("type", f"type must be one of {', '.join(KINDS)}")


def _validate_sigma(sigma: float) -> None:
    if not isinstance(sigma, (int, float)) or not math.isfinite(float(sigma)):
        raise OptionInputError("sigma", "sigma must be a finite number")
    if sigma < 0:
        raise OptionInputError("sigma", "sigma must be at least 0")


def _intrinsic(S: float, K: float, T: float, r: float, q: float, kind: str) -> float:
    forward_strike = K * math.exp(-r * T)
    spot = S * math.exp(-q * T)
    return max(0.0, spot - forward_strike) if kind == "call" else max(0.0, forward_strike - spot)


def _upper_bound(S: float, K: float, T: float, r: float, q: float, kind: str) -> float:
    return S * math.exp(-q * T) if kind == "call" else K * math.exp(-r * T)


def _d1_d2(S: float, K: float, T: float, r: float, q: float, sigma: float) -> tuple[float, float]:
    vol = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol
    return d1, d1 - vol


def bs_price(
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    sigma: float,
    kind: Literal["call", "put"] = "call",
) -> float:
    """Analytic European value; ``sigma == 0`` is the discounted intrinsic limit."""
    spot = S * math.exp(-q * T)
    strike = K * math.exp(-r * T)
    if sigma == 0:
        return max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    if kind == "call":
        return spot * _norm_cdf(d1) - strike * _norm_cdf(d2)
    return strike * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _greeks(
    S: float, K: float, T: float, r: float, q: float, sigma: float, kind: str
) -> dict[str, float]:
    spot = S * math.exp(-q * T)
    strike = K * math.exp(-r * T)
    sqrt_t = math.sqrt(T)

    if sigma == 0:
        # Limits as σ → 0: the option is worth exactly its intrinsic value and
        # behaves like a forward, so second-order sensitivities vanish.
        call_itm = spot > strike
        if kind == "call":
            n_d1 = 1.0 if call_itm else 0.0
            n_d2 = n_d1
            delta = math.exp(-q * T) * n_d1
            theta = q * spot * n_d1 - r * strike * n_d2
            rho = K * T * math.exp(-r * T) * n_d2
        else:
            n_neg_d1 = 0.0 if call_itm else 1.0
            n_neg_d2 = n_neg_d1
            delta = -math.exp(-q * T) * n_neg_d1
            theta = -q * spot * n_neg_d1 + r * strike * n_neg_d2
            rho = -K * T * math.exp(-r * T) * n_neg_d2
        gamma = 0.0
        vega = 0.0
        return {
            "delta": delta,
            "gamma": gamma,
            "vega": vega,
            "theta": theta / 365.0,
            "rho": rho * 0.01,
        }

    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    pdf_d1 = _norm_pdf(d1)
    gamma = math.exp(-q * T) * pdf_d1 / (S * sigma * sqrt_t)
    vega = S * math.exp(-q * T) * pdf_d1 * sqrt_t
    decay = -S * math.exp(-q * T) * pdf_d1 * sigma / (2.0 * sqrt_t)

    if kind == "call":
        n_d1, n_d2 = _norm_cdf(d1), _norm_cdf(d2)
        delta = math.exp(-q * T) * n_d1
        theta = decay + q * S * math.exp(-q * T) * n_d1 - r * K * math.exp(-r * T) * n_d2
        rho = K * T * math.exp(-r * T) * n_d2
    else:
        n_neg_d1, n_neg_d2 = _norm_cdf(-d1), _norm_cdf(-d2)
        delta = -math.exp(-q * T) * n_neg_d1
        theta = decay - q * S * math.exp(-q * T) * n_neg_d1 + r * K * math.exp(-r * T) * n_neg_d2
        rho = -K * T * math.exp(-r * T) * n_neg_d2

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega * 0.01,
        "theta": theta / 365.0,
        "rho": rho * 0.01,
    }


def _brent(
    f: Any, a: float, b: float, fa: float, fb: float, tol: float, max_iter: int
) -> tuple[float, int, bool]:
    """Brent's method on a bracketed root (no SciPy dependency)."""
    if fa == 0.0:
        return a, 0, True
    if fb == 0.0:
        return b, 0, True
    if fa * fb > 0.0:
        raise ValueError("root is not bracketed")
    c, fc = a, fa
    d = e = b - a
    for iteration in range(1, max_iter + 1):
        if fb * fc > 0.0:
            c, fc = a, fa
            d = e = b - a
        if abs(fc) < abs(fb):
            a, b, c = b, c, b
            fa, fb, fc = fb, fc, fb
        tol1 = 2.0 * 2.220446049250313e-16 * abs(b) + 0.5 * tol
        xm = 0.5 * (c - b)
        if abs(xm) <= tol1 or fb == 0.0:
            return b, iteration, True
        if abs(e) >= tol1 and abs(fa) > abs(fb):
            s = fb / fa
            if a == c:
                p, q = 2.0 * xm * s, 1.0 - s
            else:
                q = fa / fc
                r = fb / fc
                p = s * (2.0 * xm * q * (q - r) - (b - a) * (r - 1.0))
                q = (q - 1.0) * (r - 1.0) * (s - 1.0)
            if p > 0.0:
                q = -q
            p = abs(p)
            if 2.0 * p < min(3.0 * xm * q - abs(tol1 * q), abs(e * q)):
                e, d = d, p / q
            else:
                d = e = xm
        else:
            d = e = xm
        a, fa = b, fb
        b += d if abs(d) > tol1 else math.copysign(tol1, xm)
        fb = f(b)
    return b, max_iter, False


def _bisect(
    f: Any, a: float, b: float, fa: float, fb: float, tol: float, max_iter: int
) -> tuple[float, int, bool]:
    for iteration in range(1, max_iter + 1):
        mid = 0.5 * (a + b)
        fm = f(mid)
        if abs(fm) <= PRICE_TOL:
            return mid, iteration, True
        if 0.5 * (b - a) <= tol:
            return mid, iteration, True
        if (fa < 0.0) == (fm < 0.0):
            a, fa = mid, fm
        else:
            b, fb = mid, fm
    return 0.5 * (a + b), max_iter, False


def _warnings(S: float, K: float, T: float, kind: str) -> tuple[bool, list[str]]:
    near_expiry = T < NEAR_EXPIRY_YEARS
    messages = []
    if near_expiry:
        messages.append(
            "Less than one day to expiry: greeks are numerically unstable and should not be traded on."
        )
    return near_expiry, messages


def price(
    *,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float = 0.0,
    sigma: float,
    kind: str = "call",
) -> dict[str, Any]:
    """FR-O1: fair value, d1/d2, full greeks and the FR-O4 boundaries."""
    _validate_kind(kind)
    _validate_inputs(S, K, T, r, q)
    _validate_sigma(sigma)

    value = bs_price(S, K, T, r, q, sigma, kind)  # type: ignore[arg-type]
    intrinsic = _intrinsic(S, K, T, r, q, kind)
    near_expiry, warnings = _warnings(S, K, T, kind)
    greeks = _greeks(S, K, T, r, q, sigma, kind)
    d1, d2 = (None, None) if sigma == 0 else _d1_d2(S, K, T, r, q, sigma)

    return {
        "engine_version": ENGINE_VERSION,
        "type": kind,
        "inputs": {"S": S, "K": K, "T": T, "r": r, "q": q, "sigma": sigma},
        "price": round(value, 10),
        "intrinsic": round(intrinsic, 10),
        "time_value": round(value - intrinsic, 12),
        "d1": None if d1 is None else round(d1, 10),
        "d2": None if d2 is None else round(d2, 10),
        "greeks": {key: round(greeks[key], 10) for key in ("delta", "gamma", "vega", "theta", "rho")},
        "greek_units": GREEK_UNITS,
        "bounds": {
            "lower": round(max(0.0, intrinsic), 10),
            "upper": round(_upper_bound(S, K, T, r, q, kind), 10),
        },
        "near_expiry_unstable": near_expiry,
        "warnings": warnings,
        "model_boundaries": list(MODEL_BOUNDARIES),
        "disclaimer": (
            "European Black-Scholes-Merton value under constant volatility. "
            "A model output, not a market quote."
        ),
    }


def implied_volatility(
    *,
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float = 0.0,
    kind: str = "call",
) -> dict[str, Any]:
    """FR-O2: solve BS(σ) = market_price, refusing prices outside the band."""
    _validate_kind(kind)
    _validate_inputs(S, K, T, r, q)
    if not isinstance(market_price, (int, float)) or not math.isfinite(float(market_price)):
        raise OptionInputError("market_price", "market_price must be a finite number")

    lower = max(0.0, _intrinsic(S, K, T, r, q, kind))
    upper = _upper_bound(S, K, T, r, q, kind)
    if market_price + BOUND_TOL < lower:
        raise ImpliedVolBoundError(
            "price_below_intrinsic",
            (
                f"market_price {market_price} is below the no-arbitrage lower bound {lower:.6f} "
                "(max of 0 and intrinsic value); no implied volatility exists."
            ),
            bound=round(lower, 10),
        )
    if market_price - BOUND_TOL > upper:
        raise ImpliedVolBoundError(
            "price_above_upper_bound",
            (
                f"market_price {market_price} is above the no-arbitrage upper bound {upper:.6f}; "
                "the implied volatility would be infinite."
            ),
            bound=round(upper, 10),
        )

    near_expiry, warnings = _warnings(S, K, T, kind)
    common = {
        "engine_version": ENGINE_VERSION,
        "type": kind,
        "market_price": market_price,
        "inputs": {"S": S, "K": K, "T": T, "r": r, "q": q},
        "bounds": {"lower": round(lower, 10), "upper": round(upper, 10)},
        "search": {
            "min_sigma": MIN_SIGMA,
            "max_sigma": MAX_SIGMA,
            "sigma_tolerance": SIGMA_TOL,
            "max_iterations": MAX_ITERATIONS,
        },
        "near_expiry_unstable": near_expiry,
        "model_boundaries": list(MODEL_BOUNDARIES),
        "disclaimer": (
            "Implied volatility is the constant σ that reproduces the supplied price under "
            "Black-Scholes. A model output, not a market quote."
        ),
    }

    if market_price <= lower + BOUND_TOL:
        # The price is the discounted intrinsic value: σ = 0 is the answer and
        # the solver would otherwise search an interval that excludes it.
        return {
            **common,
            "implied_volatility": 0.0,
            "converged": True,
            "iterations": 0,
            "solver": "boundary",
            "model_price": round(lower, 10),
            "price_error": round(lower - market_price, 12),
            "warnings": warnings + ["Price equals intrinsic value: implied volatility is 0."],
        }
    if market_price >= upper - BOUND_TOL:
        model_price = bs_price(S, K, T, r, q, MAX_SIGMA, kind)  # type: ignore[arg-type]
        return {
            **common,
            "implied_volatility": MAX_SIGMA,
            "converged": False,
            "iterations": 0,
            "solver": "boundary",
            "model_price": round(model_price, 10),
            "price_error": round(model_price - market_price, 12),
            "warnings": warnings
            + [
                "Price is at or above the asymptotic upper bound; implied volatility is reported "
                f"at the search ceiling {MAX_SIGMA} and did not converge."
            ],
        }

    def objective(sigma: float) -> float:
        return bs_price(S, K, T, r, q, sigma, kind) - market_price  # type: ignore[arg-type]

    fa, fb = objective(MIN_SIGMA), objective(MAX_SIGMA)
    sigma, iterations, converged = _brent(
        objective, MIN_SIGMA, MAX_SIGMA, fa, fb, SIGMA_TOL, MAX_ITERATIONS
    )
    solver = "brent"
    if not converged or not (MIN_SIGMA <= sigma <= MAX_SIGMA) or not math.isfinite(sigma):
        sigma, extra, converged = _bisect(
            objective, MIN_SIGMA, MAX_SIGMA, fa, fb, SIGMA_TOL, MAX_ITERATIONS
        )
        iterations += extra
        solver = "bisection"
    if not converged:
        warnings = warnings + [
            f"Implied volatility did not converge within {MAX_ITERATIONS} iterations; "
            "the value is the best estimate from the bracketing interval."
        ]

    model_price = bs_price(S, K, T, r, q, sigma, kind)  # type: ignore[arg-type]
    return {
        **common,
        "implied_volatility": round(sigma, 10),
        "converged": converged,
        "iterations": iterations,
        "solver": solver,
        "model_price": round(model_price, 10),
        "price_error": round(model_price - market_price, 12),
        "warnings": warnings,
    }


price_option = price
