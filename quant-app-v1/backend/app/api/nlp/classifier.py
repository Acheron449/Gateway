from __future__ import annotations


def categorize_global_event(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("rate", "inflation", "cpi", "gdp", "central bank")):
        return "macro"
    if any(token in lowered for token in ("war", "election", "sanction", "tariff")):
        return "geopolitical"
    if any(token in lowered for token in ("earnings", "guidance", "merger", "acquisition")):
        return "corporate"
    return "general"