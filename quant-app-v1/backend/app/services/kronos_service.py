"""Optional adapter for the upstream Kronos forecasting repository.

Kronos is deliberately loaded lazily: downloading a Hugging Face model is a
deployment concern and must never make the rest of the API unavailable.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

import pandas as pd


class KronosUnavailable(RuntimeError):
    """Raised when the optional Kronos source checkout or model is unavailable."""


def bars_to_kronos_frame(bars: list[dict]) -> tuple[pd.DataFrame, pd.Series]:
    """Convert Gateway chart bars to Kronos' lower-case OHLCV input contract."""
    frame = pd.DataFrame(bars).copy()
    if frame.empty:
        raise ValueError("bars must contain at least one OHLC candle")

    aliases = {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume", "amount": "amount"}
    renamed: dict[str, str] = {}
    for column in frame.columns:
        key = str(column).lower()
        if key in aliases:
            renamed[column] = aliases[key]
    frame = frame.rename(columns=renamed)
    missing = {"open", "high", "low", "close"}.difference(frame.columns)
    if missing:
        raise ValueError(f"bars are missing required OHLC fields: {', '.join(sorted(missing))}")

    timestamp_column = next((c for c in ("timestamp", "time", "datetime", "date") if c in frame.columns), None)
    if timestamp_column is None:
        timestamps = pd.Series(pd.date_range("2000-01-01", periods=len(frame), freq="D"))
    else:
        raw = frame[timestamp_column]
        timestamps = pd.to_datetime(raw, unit="s" if pd.api.types.is_numeric_dtype(raw) else None, errors="coerce")
        if timestamps.isna().any():
            raise ValueError("every bar timestamp must be a valid date or Unix-second value")
        timestamps = pd.Series(timestamps)

    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[["open", "high", "low", "close"]].isna().any().any():
        raise ValueError("OHLC values must be numeric")
    return frame[[c for c in ("open", "high", "low", "close", "volume", "amount") if c in frame]], timestamps


@lru_cache(maxsize=1)
def _predictor():
    repo_path = os.getenv("KRONOS_REPO_PATH")
    if repo_path:
        path = Path(repo_path).expanduser().resolve()
        if not (path / "model").is_dir():
            raise KronosUnavailable("KRONOS_REPO_PATH must point to a Kronos repository checkout")
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    try:
        from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore
    except ImportError as exc:
        raise KronosUnavailable(
            "Kronos is not installed. Clone https://github.com/shiyu-coder/Kronos, set KRONOS_REPO_PATH, "
            "and install its requirements."
        ) from exc

    models_dir = Path(__file__).resolve().parents[2] / "models" / "kronos"
    local_tokenizer = models_dir / "Kronos-Tokenizer-base"
    local_model = models_dir / "Kronos-base"
    # Local artifacts are the deployment default. Environment variables still
    # accept Hugging Face identifiers or alternate filesystem paths.
    tokenizer_name = os.getenv(
        "KRONOS_TOKENIZER", str(local_tokenizer) if local_tokenizer.is_dir() else "NeoQuasar/Kronos-Tokenizer-base"
    )
    model_name = os.getenv(
        "KRONOS_MODEL", str(local_model) if local_model.is_dir() else "NeoQuasar/Kronos-base"
    )
    try:
        tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
        model = Kronos.from_pretrained(model_name)
        return KronosPredictor(model, tokenizer, max_context=int(os.getenv("KRONOS_MAX_CONTEXT", "512")))
    except Exception as exc:
        raise KronosUnavailable(f"Unable to load Kronos model '{model_name}': {exc}") from exc


def forecast(bars: list[dict], horizon: int, frequency: str = "D", sample_count: int = 1) -> pd.DataFrame:
    if not 1 <= horizon <= 240:
        raise ValueError("horizon must be between 1 and 240")
    frame, timestamps = bars_to_kronos_frame(bars)
    if len(frame) < 20:
        raise ValueError("at least 20 historical candles are required for a Kronos forecast")
    future = pd.Series(pd.date_range(timestamps.iloc[-1], periods=horizon + 1, freq=frequency)[1:])
    return _predictor().predict(
        df=frame,
        x_timestamp=timestamps,
        y_timestamp=future,
        pred_len=horizon,
        T=1.0,
        top_p=0.9,
        sample_count=max(1, min(int(sample_count), 20)),
    )
