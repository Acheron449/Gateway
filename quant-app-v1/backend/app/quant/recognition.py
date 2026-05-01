from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class PatternSignal:
    type: str
    confidence: float
    direction: str

    def to_dict(self) -> dict:
        return asdict(self)


def find_pivots(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    highs = df["High"]
    lows = df["Low"]

    rolling_high = highs.rolling(window * 2 + 1, center=True).max()
    rolling_low = lows.rolling(window * 2 + 1, center=True).min()

    pivot_high = highs.eq(rolling_high)
    pivot_low = lows.eq(rolling_low)

    pivots = df.loc[pivot_high | pivot_low, ["High", "Low"]].copy()
    pivots["pivot_type"] = "low"
    pivots.loc[pivot_high[pivot_high].index, "pivot_type"] = "high"
    return pivots


def detect_head_and_shoulders(pivots: pd.DataFrame) -> list[PatternSignal]:
    highs = pivots[pivots["pivot_type"] == "high"]["High"].dropna().tolist()
    if len(highs) < 3:
        return []

    left, head, right = highs[-3:]
    shoulder_balance = abs(left - right) / max(left, right, 1)
    head_ratio = (head - max(left, right)) / max(head, 1)

    if head > left and head > right and shoulder_balance < 0.06 and head_ratio > 0.02:
        confidence = min(0.95, 0.75 + head_ratio)
        return [PatternSignal(type="HeadAndShoulders", confidence=confidence, direction="Bearish")]

    return []