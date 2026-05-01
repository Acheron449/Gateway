from __future__ import annotations

import math
import re
from datetime import datetime, timezone

POSITIVE_WORDS = {"beat", "growth", "upgrade", "rally", "surge", "profit", "strong"}
NEGATIVE_WORDS = {"miss", "downgrade", "drop", "slump", "weak", "loss", "lawsuit"}
STOP_WORDS = {"the", "a", "an", "and", "or", "to", "for", "of", "in", "on"}


def clean_headline(text: str) -> str:
    lowered = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
    tokens = [token for token in lowered.split() if token not in STOP_WORDS and not token.startswith("$")]
    return " ".join(tokens)


def score_text_sentiment(cleaned_text: str) -> float:
    tokens = cleaned_text.split()
    if not tokens:
        return 0.0
    pos = sum(1 for token in tokens if token in POSITIVE_WORDS)
    neg = sum(1 for token in tokens if token in NEGATIVE_WORDS)
    raw = (pos - neg) / max(len(tokens), 1)
    return max(-1.0, min(1.0, raw * 3))


def process_news_sentiment(headline: str, timestamp: datetime) -> float:
    cleaned_text = clean_headline(headline)
    raw_score = score_text_sentiment(cleaned_text)

    now = datetime.now(timezone.utc)
    ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    hours_elapsed = max(0.0, (now - ts).total_seconds() / 3600)
    decay_factor = math.exp(-0.1 * hours_elapsed)
    return raw_score * decay_factor


def get_latest_score_for_ticker(ticker: str) -> float:
    headline = f"{ticker} posts strong growth outlook"
    return process_news_sentiment(headline, datetime.now(timezone.utc))