"""User research documents for the Agentic Lab.

Three entry paths, one store: typed notes, uploaded files (.txt/.md/.csv),
and drafts a model produced through the harness. Research can then be fed
into LLM strategy prompts as background.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


_SETTINGS_DIR = Path(__file__).resolve().parent.parent / "settings"
_SETTINGS_FILE = _SETTINGS_DIR / "agentic_research.json"

MAX_DOCS = 100
MAX_CONTENT_CHARS = 100_000


def _load() -> list[dict[str, Any]]:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    if not _SETTINGS_FILE.exists():
        return []
    try:
        with _SETTINGS_FILE.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _save(docs: list[dict[str, Any]]) -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    temporary = _SETTINGS_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(docs, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, _SETTINGS_FILE)


def list_docs() -> list[dict[str, Any]]:
    return _load()


def get_doc(doc_id: str) -> Optional[dict[str, Any]]:
    return next((doc for doc in _load() if doc.get("id") == doc_id), None)


def save_doc(
    *,
    title: str,
    content: str,
    source: str,
    symbol: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    doc_id: Optional[str] = None,
) -> dict[str, Any]:
    text = (content or "").strip()[:MAX_CONTENT_CHARS]
    if not text:
        raise ValueError("Research content must not be empty")
    if source not in ("typed", "uploaded", "model"):
        raise ValueError("source must be typed, uploaded, or model")

    docs = _load()
    existing = next((d for d in docs if d.get("id") == doc_id), None) if doc_id else None
    record = {
        "id": existing["id"] if existing else uuid.uuid4().hex[:10],
        "title": (title or "Untitled research").strip()[:120],
        "content": text,
        "source": source,
        "symbol": (symbol or "").strip().upper() or None,
        "provider": provider,
        "model": model,
        "created_at": existing["created_at"] if existing else datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "chars": len(text),
    }
    docs = [d for d in docs if d.get("id") != record["id"]]
    docs.insert(0, record)
    _save(docs[:MAX_DOCS])
    return record


def delete_doc(doc_id: str) -> bool:
    docs = _load()
    remaining = [d for d in docs if d.get("id") != doc_id]
    if len(remaining) == len(docs):
        return False
    _save(remaining)
    return True


def research_prompt(topic: str, symbol: Optional[str] = None) -> list[dict[str, str]]:
    """Harness-style prompt that asks a model for a research brief."""
    target = f" about {symbol.upper()}" if symbol else ""
    system = (
        "You are a buy-side research analyst. Write concise, well-structured "
        "market research in Markdown: thesis, key drivers, risks, and a "
        "bottom line. Use only the information given plus your general "
        "knowledge, and clearly label speculation."
    )
    user = (
        f"Write a research brief{target} on: {topic.strip()[:400]}. "
        "Sections: Overview, Bull case, Bear case, Key catalysts, Risks, Bottom line."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def combined_context(symbol: Optional[str] = None) -> str:
    """All saved research (optionally symbol-scoped) as one context block."""
    docs = _load()
    relevant = [d for d in docs if not symbol or not d.get("symbol") or d["symbol"] == symbol.upper()]
    if not relevant:
        return ""
    blocks = ["Saved research library:"]
    for doc in relevant[:8]:
        blocks.append(f"\n## {doc['title']} ({doc['source']}, {doc['created_at'][:10]})\n{doc['content'][:4000]}")
    return "\n".join(blocks)
