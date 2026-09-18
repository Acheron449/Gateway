from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _prices_frame(prices: dict[str, list[float]]) -> pd.DataFrame:
    if len(prices) < 2:
        raise ValueError("prices must contain at least two assets")
    frame = pd.DataFrame(prices).apply(pd.to_numeric, errors="coerce").dropna()
    if len(frame) < 20:
        raise ValueError("at least 20 aligned observations per asset are required")
    if (frame <= 0).any().any():
        raise ValueError("prices must be positive")
    return frame


@router.post("/optimize")
async def optimize_portfolio(payload: dict[str, Any]) -> dict[str, Any]:
    """Produce long-only HRP or mean-risk weights with skfolio."""
    try:
        from skfolio.optimization import HierarchicalRiskParity, MeanRisk  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="skfolio is not installed; run pip install -U skfolio") from exc

    try:
        prices = _prices_frame(payload.get("prices", {}))
        returns = prices.pct_change().dropna()
        method = str(payload.get("method", "hrp")).lower()
        if method == "hrp":
            model = HierarchicalRiskParity()
        elif method in {"mean_risk", "mean-risk"}:
            model = MeanRisk()
        else:
            raise ValueError("method must be 'hrp' or 'mean_risk'")
        model.fit(returns)
        weights = np.asarray(model.weights_, dtype=float)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"skfolio optimization failed: {exc}") from exc

    return {
        "provider": "skfolio",
        "method": method,
        "observations": len(returns),
        "weights": {asset: round(float(weight), 8) for asset, weight in zip(returns.columns, weights)},
    }
