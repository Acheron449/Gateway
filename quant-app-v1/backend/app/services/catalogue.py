"""Versioned US-equities instrument catalogue with typed records and provenance.

The catalogue is a static, versioned snapshot used to replace hard-coded symbol
search. It is intentionally small and free; expanding coverage requires a
licensed/permissioned reference source, which is a roadmap Phase 2 decision.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import TypeAdapter

from app.models import Instrument, Provenance

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "data" / "instruments" / "catalogue_v1.json"

_instrument_list = TypeAdapter(list[Instrument])


class InstrumentCatalogueError(RuntimeError):
    """The instrument catalogue is missing, malformed or unsupported."""


def _load_catalogue(path: Path) -> tuple[dict, Provenance, list[Instrument]]:
    if not path.exists():
        raise InstrumentCatalogueError(f"Instrument catalogue not found at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstrumentCatalogueError(f"Instrument catalogue is not valid JSON: {exc}") from exc

    provenance_kwargs = {
        "source": str(raw.get("source") or "gateway-instrument-catalogue"),
        "provider_version": str(raw.get("provider_version") or "gateway-catalogue-v1"),
        "data_time": raw.get("generated_at"),
        "coverage": str(raw.get("coverage") or ""),
        "delay_seconds": raw.get("delay_seconds"),
        "entitlement": str(raw.get("entitlement") or "internal-snapshot-free"),
    }
    provenance = Provenance.model_validate(provenance_kwargs)

    metadata = {
        "schema_version": raw.get("schema_version", "1.0"),
        "catalogue_version": raw.get("catalogue_version", "0.0.0"),
        "description": raw.get("description", ""),
    }
    raw_records = raw.get("instruments", [])
    try:
        records = _instrument_list.validate_python(
            [
                {**record, "provenance": provenance}
                for record in raw_records
                if isinstance(record, dict)
            ]
        )
    except Exception as exc:
        raise InstrumentCatalogueError(f"Instrument catalogue records are invalid: {exc}") from exc

    return metadata, provenance, records


@lru_cache(maxsize=1)
def load_catalogue(path: Path | None = None) -> dict:
    """Load and validate the versioned catalogue once per process."""
    catalogue_path = Path(path) if path is not None else CATALOGUE_PATH
    metadata, provenance, instruments = _load_catalogue(catalogue_path)
    return {
        "metadata": metadata,
        "provenance": provenance,
        "instruments": instruments,
    }


def _normalize_query(query: str) -> str:
    return "".join(ch for ch in (query or "").strip().upper() if ch.isalnum() or ch in ".-")[:20]


def list_instruments() -> list[Instrument]:
    return list(load_catalogue()["instruments"])


def get_instrument(symbol: str) -> Instrument | None:
    lookup_symbol = _normalize_query(symbol)
    for instrument in list_instruments():
        if instrument.symbol == lookup_symbol:
            return instrument
    return None


def search_instruments(query: str, *, limit: int = 20) -> list[Instrument]:
    """Search by symbol prefix or case-insensitive name fragment."""
    needle = _normalize_query(query)
    matches: list[Instrument] = []
    for instrument in list_instruments():
        if needle and (instrument.symbol.startswith(needle) or needle in instrument.name.upper()):
            matches.append(instrument)
            if len(matches) >= max(1, min(int(limit), 50)):
                break
    return matches


def catalogue_info() -> dict:
    """Non-secret catalogue identity: version, schema, source and provenance."""
    catalogue = load_catalogue()
    return {
        "schema_version": catalogue["metadata"]["schema_version"],
        "catalogue_version": catalogue["metadata"]["catalogue_version"],
        "description": catalogue["metadata"]["description"],
        "provenance": catalogue["provenance"].model_dump(mode="json"),
        "instrument_count": len(catalogue["instruments"]),
    }