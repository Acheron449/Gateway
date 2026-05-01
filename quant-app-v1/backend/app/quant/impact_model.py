from __future__ import annotations


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def calculate_final_signal(patterns: list[dict], sentiment_score: float) -> dict:
    if not patterns:
        return {"confidence": _clamp(0.5 + sentiment_score * 0.2), "direction": "Neutral"}

    best = max(patterns, key=lambda p: p.get("confidence", 0.0))
    base_confidence = float(best.get("confidence", 0.5))
    direction = best.get("direction", "Neutral")

    adjustment = sentiment_score * 0.2
    if direction == "Bearish":
        adjustment *= -1

    final_confidence = _clamp(base_confidence + adjustment)
    return {"confidence": final_confidence, "direction": direction}