#!/usr/bin/env python3
"""
verify_paper_trade_reconciliation.py

Purpose
-------
Gate check for Phase 4 (Live-execution prerequisites): verifies that paper-trade
records reconcile against expected/reference fills within tolerance, over a
statistically meaningful sample.


Pass criteria (hard-coded gate, override only via --min-trades / --max-mismatch-pct):
    - sample size  >= 1000 trades
    - mismatch rate < 0.1%  (i.e. < 0.001)


A "mismatch" is any trade where paper-side and reference-side records disagree on
symbol, side, quantity, or price (within a configurable price tolerance), or where
a trade exists on one side but not the other (an orphan).


Input assumptions
------------------
Two input files, CSV or JSON Lines, each containing one row per trade/fill:


  paper trades (from your paper-trading engine):
      order_id, symbol, side, qty, price, timestamp


  reference fills (from broker/exchange simulator or source-of-truth ledger):
      order_id, symbol, side, qty, price, timestamp


order_id is assumed to be the join key. If your schema differs, adjust the
--paper-* / --ref-* column-mapping flags below rather than editing
the reconciliation logic.


This script does NOT execute trades or touch any live system. It only reads
two record sets and reports on reconciliation. It is meant to be run in CI
or as a manual gate before Phase 4/5 can be marked verified.


Exit codes
----------
0  = PASS (sample size and mismatch rate both within tolerance)
1  = FAIL (sample too small and/or mismatch rate too high)
2  = ERROR (bad input, missing files, unparseable records)


Usage
-----
    python verify_paper_trade_reconciliation.py \\
        --paper paper_trades.csv \\
        --reference reference_fills.csv \\
        --report reconciliation_report.json


    python verify_paper_trade_reconciliation.py \\
        --paper paper_trades.jsonl --paper-format jsonl \\
        --reference reference_fills.jsonl --reference-format jsonl
"""


import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple




# --------------------------------------------------------------------------- #
# Config / defaults
# --------------------------------------------------------------------------- #


DEFAULT_MIN_TRADES = 1000
DEFAULT_MAX_MISMATCH_PCT = 0.1  # percent, i.e. 0.1% = 0.001 fraction
DEFAULT_PRICE_TOLERANCE = Decimal("0.0001")  # relative tolerance (0.01%)


@dataclass
class ColumnMap:
    order_id: str = "order_id"
    symbol: str = "symbol"
    side: str = "side"
    qty: str = "qty"
    price: str = "price"
    timestamp: str = "timestamp"


@dataclass
class Trade:
    order_id: str
    symbol: str
    side: str
    qty: Decimal
    price: Decimal
    timestamp: str
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Mismatch:
    order_id: str
    kind: str          # "orphan_paper" | "orphan_reference" | "field_mismatch"
    detail: str




# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_records(path: Path, fmt: str) -> List[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")


    if fmt == "csv":
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)


    if fmt == "jsonl":
        records = []
        with path.open(encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{line_num}: invalid JSON — {e}") from e
        return records


    if fmt == "json":
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # allow {"trades": [...]}-style wrappers
            for key in ("trades", "records", "data"):
                if key in data and isinstance(data[key], list):
                    return data[key]
            raise ValueError(f"{path}: JSON object has no recognizable list field")
        if isinstance(data, list):
            return data
        raise ValueError(f"{path}: unsupported JSON structure")


    raise ValueError(f"Unsupported format: {fmt}")


def to_decimal(value, field_name: str, order_id: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as e:
        raise ValueError(
            f"order_id={order_id}: could not parse '{field_name}'={value!r} as a number"
        ) from e




def normalize(records: List[dict], cmap: ColumnMap, source_label: str) -> Dict[str, Trade]:
    """Parse raw records into Trade objects keyed by order_id.
    Raises on missing required fields; duplicate order_ids are flagged and the
    first occurrence wins (duplicates are reported separately)."""
    trades: Dict[str, field=""
    trades: ...?
</c
</c

</c
</c
</c