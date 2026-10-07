"""Durable storage for encrypted provider API keys in Supabase.

Why this exists: on Vercel the function filesystem is ephemeral, so keys
saved from the UI used to live in per-instance ``/tmp`` and vanished when
the instance recycled. Supabase Postgres now holds them durably — as
**ciphertext only**: keys are Fernet-encrypted app-side with
``GATEWAY_PROVIDER_KEY`` before they leave the process, so a leaked backup,
dashboard session or SQL injection yields nothing usable. Table
``gateway_provider_keys`` has RLS enabled with no policies (anon/authenticated
reads return ``[]``) — access goes exclusively through the secret-gated
SECURITY DEFINER RPCs ``gw_list_provider_keys`` / ``gw_upsert_provider_key`` /
``gw_delete_provider_key``, mirroring the ``gw_*`` auth RPCs.

Layering (same rule as ``database.py``'s Supabase mode):
* Supabase configured (``SUPABASE_URL`` + ``SUPABASE_KEY`` +
  ``SUPABASE_RPC_SECRET`` all set) ⇒ Supabase is authoritative; the
  per-instance settings file remains the read fallback while the RPC layer
  is unreachable.
* Not configured (local dev, tests) ⇒ local file only, zero network calls.

Reads are cached in memory per process for ``_TTL`` seconds so the hot path
(``get_provider()`` runs on every quote/news request) hits the network at
most once per window. ``load()`` never raises — an outage degrades to the
last snapshot or the caller's local file; ``save()``/``delete()`` raise
``RuntimeError`` so a key the UI thinks it saved is never silently dropped
(routes map that to HTTP 503).
"""

from __future__ import annotations

import time
from typing import Any, Optional

from app.services.database import _sb_rpc, _supabase_enabled

# How long a fetched snapshot serves reads before re-fetching. Bounds how
# stale *another* instance's save can look (save() refreshes its own copy
# immediately) while keeping the hot path at ≤1 outbound call per window.
_TTL = 60.0

# store -> (fetched_at, {name: {"ciphertext": str | None, "payload": dict | None}})
_cache: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}

# Stores already checked for a one-time backfill this process, so a stale
# local copy can be promoted at most once per instance lifetime (never on
# every read).
_backfilled: set[str] = set()


def enabled() -> bool:
    """True when the Supabase trio is configured (read at call time)."""
    return _supabase_enabled()


def reset_cache() -> None:
    """Drop all cached snapshots (tests / after config changes)."""
    _cache.clear()
    _backfilled.clear()


def load(store: str) -> Optional[dict[str, dict[str, Any]]]:
    """All entries for one store (``market`` / ``llm``).

    Returns ``None`` when Supabase is not configured or unreachable, so the
    caller can fall back to its local settings file. Never raises: reads sit
    on hot request paths that must not 500 because of the key store.
    """
    if not enabled():
        return None
    now = time.monotonic()
    cached = _cache.get(store)
    if cached is not None and now - cached[0] < _TTL:
        return dict(cached[1])
    try:
        rows = _sb_rpc("gw_list_provider_keys", {"p_store": store})
    except (RuntimeError, ValueError, OSError):
        if cached is not None:
            # Unreachable: serve the last snapshot and back off for a TTL
            # instead of hammering a dead endpoint on every request.
            _cache[store] = (now, cached[1])
            return dict(cached[1])
        return None
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("name"):
            continue
        payload = row.get("payload")
        mapping[str(row["name"])] = {
            "ciphertext": row.get("ciphertext") or None,
            "payload": payload if isinstance(payload, dict) else None,
        }
    _cache[store] = (now, mapping)
    return mapping


def _as_entry(value: Any) -> dict[str, Any]:
    """Normalize a local settings value to {ciphertext, payload}.

    Registry files hold bare ciphertext strings; LLM files hold dicts whose
    ``api_key`` field is the ciphertext and everything else is payload.
    """
    if isinstance(value, str):
        return {"ciphertext": value, "payload": None}
    if isinstance(value, dict):
        api_key = value.get("api_key")
        payload = {k: v for k, v in value.items() if k != "api_key"}
        return {
            "ciphertext": api_key if isinstance(api_key, str) else None,
            "payload": payload or None,
        }
    return {"ciphertext": None, "payload": None}


def load_with_backfill(store: str, local: dict[str, Any]) -> Optional[dict[str, dict[str, Any]]]:
    """Load the durable snapshot, promoting pre-existing local entries first.

    Guarantees old data stays persistent across updates: keys/settings that
    were written to the per-instance file *before* Supabase persistence
    existed are pushed up the first time this code runs against an empty
    remote store, so they survive instance recycling and future deploys.
    Backfill runs at most once per process and only when Supabase reports
    zero rows for the store — it can never resurrect a row that was
    deliberately deleted once the store holds anything. Never raises: the
    read path must not fail because a promotion write failed (the next cold
    start retries it).
    """
    snapshot = load(store)
    if snapshot is None or snapshot or store in _backfilled or not local:
        return snapshot
    pushable = [
        (str(name), _as_entry(value))
        for name, value in local.items()
        if name
    ]
    pushable = [
        (name, entry)
        for name, entry in pushable
        if entry["ciphertext"] or entry["payload"]
    ]
    if not pushable:
        _backfilled.add(store)
        return snapshot
    for name, entry in pushable:
        try:
            save(store, name, entry["ciphertext"], payload=entry["payload"])
        except (RuntimeError, ValueError, OSError):
            # Promotion write failed: if at least one row landed the store is
            # non-empty (authority moved there); if none did, the store stays
            # eligible and the next read after the TTL retries the whole set.
            # Never raise — this runs on hot read paths.
            return load(store)
    _backfilled.add(store)
    return load(store)


def save(
    store: str,
    name: str,
    ciphertext: Optional[str],
    payload: Optional[dict[str, Any]] = None,
) -> None:
    """Upsert one entry (remote-first). Raises RuntimeError on failure."""
    if not enabled():
        return
    _sb_rpc(
        "gw_upsert_provider_key",
        {
            "p_store": store,
            "p_name": name,
            "p_ciphertext": ciphertext,
            "p_payload": payload,
        },
    )
    cached = _cache.get(store)
    if cached is not None:
        entries = dict(cached[1])
        entries[name] = {"ciphertext": ciphertext, "payload": payload}
        _cache[store] = (time.monotonic(), entries)


def delete(store: str, name: str) -> None:
    """Remove one entry. Raises RuntimeError on failure."""
    if not enabled():
        return
    _sb_rpc(
        "gw_delete_provider_key",
        {"p_store": store, "p_name": name},
    )
    cached = _cache.get(store)
    if cached is not None:
        entries = dict(cached[1])
        entries.pop(name, None)
        _cache[store] = (time.monotonic(), entries)
