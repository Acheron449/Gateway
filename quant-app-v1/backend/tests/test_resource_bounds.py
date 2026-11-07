"""NFR-12 input bounds for Monte Carlo and Kronos."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1 import quant as quant_api
from app.api.v1.forecast import kronos_forecast
from app.services import kronos_service
from app.services import quant_monte_carlo as engine


def test_monte_carlo_request_rejects_oversized_observation_lists() -> None:
    too_many = [0.01] * (engine.MAX_OBSERVATIONS + 1)

    with pytest.raises(ValidationError):
        quant_api.MonteCarloRequest(returns=too_many, paths=100, horizon=10)
    with pytest.raises(ValidationError):
        quant_api.MonteCarloRequest(equity_curve=too_many, paths=100, horizon=10)

    allowed = quant_api.MonteCarloRequest(returns=[0.01] * 2, paths=100, horizon=10)
    assert len(allowed.returns or []) == 2


def test_monte_carlo_service_rejects_oversized_series() -> None:
    with pytest.raises(ValueError, match="at most 20,000 observations"):
        engine._validate_series(
            [0.01] * (engine.MAX_OBSERVATIONS + 1), label="returns", floor=-1.0
        )


def test_kronos_service_rejects_oversized_bar_history() -> None:
    with pytest.raises(ValueError, match="2,000 historical candles"):
        kronos_service.forecast([{}] * (kronos_service.MAX_BARS + 1), horizon=20)


@pytest.mark.asyncio
async def test_kronos_route_maps_oversized_history_to_422() -> None:
    with pytest.raises(HTTPException) as rejected:
        await kronos_forecast(
            {"bars": [{}] * (kronos_service.MAX_BARS + 1), "horizon": 20}
        )
    assert rejected.value.status_code == 422
