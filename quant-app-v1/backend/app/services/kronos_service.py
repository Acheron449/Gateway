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


def local_server_url() -> str:
    """Base URL of a locally running Kronos inference server (item 12).

    Set ``KRONOS_SERVER_URL`` to point at your own server; the default matches
    a local ``kronos_server`` process exposing ``/health`` and ``/predict``.
    """
    return (os.getenv("KRONOS_SERVER_URL", "").strip() or "http://127.0.0.1:8765").rstrip("/")


_local_status_cache: tuple[float, dict] | None = None


def _local_server_enabled() -> bool:
    return os.getenv("KRONOS_LOCAL_SERVER", "1").strip().lower() not in {"0", "false", "off", "no"}


def local_server_status(timeout: float = 0.8, *, refresh: bool = False) -> dict:
    """Probe the local model server so the UI can show the connection state.

    Probing costs a socket round-trip, so the result is memoised for a few
    seconds — forecasts should not each pay the probe when the server is down.
    """
    global _local_status_cache
    if not _local_server_enabled():
        return {"configured_url": local_server_url(), "reachable": False, "detail": "disabled by KRONOS_LOCAL_SERVER", "enabled": False}

    import time as _time

    now = _time.monotonic()
    if not refresh and _local_status_cache is not None and now - _local_status_cache[0] < 8:
        return _local_status_cache[1]

    url = local_server_url()
    try:
        import httpx

        response = httpx.get(f"{url}/health", timeout=timeout)
        reachable = response.status_code == 200
        detail = None if reachable else f"HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001 — any transport error just means "not up"
        reachable = False
        detail = str(exc) or type(exc).__name__
    status = {
        "configured_url": url,
        "reachable": reachable,
        "detail": detail,
        "enabled": True,
    }
    _local_status_cache = (now, status)
    return status


def _forecast_from_local_server(
    bars: list[dict], horizon: int, frequency: str, sample_count: int
) -> pd.DataFrame:
    """POST candles to the local model server and rebuild a Kronos-shaped frame."""
    import httpx

    url = local_server_url()
    response = httpx.post(
        f"{url}/predict",
        json={
            "bars": bars,
            "horizon": horizon,
            "frequency": frequency,
            "sample_count": sample_count,
        },
        timeout=float(os.getenv("KRONOS_LOCAL_SERVER_TIMEOUT", "60")),
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("forecast") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise KronosUnavailable("Local Kronos server returned no forecast rows")

    frame = pd.DataFrame(rows)
    # The server may label the date column `index`, `time` or `date`.
    stamp = next((c for c in ("index", "time", "date", "timestamp") if c in frame.columns), None)
    if stamp is None:
        raise KronosUnavailable("Local Kronos server response is missing a date column")
    dates = pd.to_datetime(frame.pop(stamp), errors="coerce")
    if dates.isna().any():
        raise KronosUnavailable("Local Kronos server returned unparseable dates")

    for column in ("open", "high", "low", "close", "volume"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    missing = {"open", "high", "low", "close"}.difference(frame.columns)
    if missing:
        raise KronosUnavailable(
            f"Local Kronos server response is missing: {', '.join(sorted(missing))}"
        )
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in frame]
    out = frame[keep].copy()
    # Unnamed DatetimeIndex so the API's reset_index() yields an `index` key.
    out.index = pd.DatetimeIndex(dates)
    return out


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
    else:
        # Default to the checkout vendored next to the backend so predictions
        # work out of the box; KRONOS_REPO_PATH still overrides it.
        vendored = Path(__file__).resolve().parents[2] / "vendor" / "Kronos"
        if (vendored / "model").is_dir() and str(vendored) not in sys.path:
            sys.path.insert(0, str(vendored))
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


def forecast_in_process(
    bars: list[dict], horizon: int, frequency: str = "D", sample_count: int = 1
) -> pd.DataFrame:
    """Load the Kronos model in this process and predict.

    Split out from :func:`forecast` so a locally running model server can call
    it without re-probing itself and recursing.
    """
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


def forecast(bars: list[dict], horizon: int, frequency: str = "D", sample_count: int = 1) -> pd.DataFrame:
    """Forecast candles, preferring a locally running Kronos model server."""
    if not 1 <= horizon <= 240:
        raise ValueError("horizon must be between 1 and 240")
    if len(bars) < 20:
        raise ValueError("at least 20 historical candles are required for a Kronos forecast")

    # Prefer a locally running model server when one is reachable (item 12),
    # then fall back to loading the model in-process.
    if _local_server_enabled() and local_server_status()["reachable"]:
        try:
            return _forecast_from_local_server(bars, horizon, frequency, sample_count)
        except KronosUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — degrade to the in-process path
            import logging

            logging.getLogger("gateway.kronos").warning(
                "Local Kronos server failed (%s) — falling back to in-process model", exc
            )

    return forecast_in_process(bars, horizon, frequency, sample_count)
