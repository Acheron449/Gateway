"""Automatic trade logging into the journal.

Every fill — paper or live — can be recorded in ``journal_entries`` so the
Journal view can compare actual vs. paper performance. Entries written here
are deduplicated by ``fill_id`` and carry a ``source`` of ``paper``,
``actual`` or ``manual`` (manual = created by the user from the UI).

This module owns the journal schema so both the API router and portfolio
services can share it without importing FastAPI code.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from app.services.database import get_connection, init_db

JOURNAL_SOURCES = ("paper", "actual", "manual")

_JOURNAL_DDL = """
    CREATE TABLE IF NOT EXISTS journal_entries (
        id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
        quantity REAL NOT NULL,
        entry_price REAL NOT NULL,
        entry_time TEXT NOT NULL,
        hypothesis TEXT NOT NULL,
        entry_context TEXT DEFAULT '',
        exit_price REAL,
        exit_time TEXT,
        exit_context TEXT,
        pnl REAL,
        pnl_pct REAL,
        rating INTEGER CHECK(rating BETWEEN 1 AND 5),
        lessons TEXT,
        tags TEXT DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed')),
        source TEXT NOT NULL DEFAULT 'manual',
        fill_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
"""


def ensure_journal_tables() -> None:
    """Create the journal table (with source/fill_id) and migrate old copies."""
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_JOURNAL_DDL)

        # Migrate tables created before the source/fill_id columns existed.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)")}
        if "source" not in columns:
            cur.execute("ALTER TABLE journal_entries ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        if "fill_id" not in columns:
            cur.execute("ALTER TABLE journal_entries ADD COLUMN fill_id TEXT")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_symbol ON journal_entries(symbol)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_status ON journal_entries(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_created ON journal_entries(created_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_journal_source ON journal_entries(source)")
        # Fill dedupe: every applied fill is recorded exactly once, including
        # partial exits (which don't carry a fill_id on the entry row itself).
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS journal_fill_log (
                fill_id TEXT PRIMARY KEY,
                entry_id TEXT,
                source TEXT NOT NULL DEFAULT 'paper',
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _iso(value: datetime | str | None) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def already_logged(fill_id: str) -> bool:
    """True when this fill id has already been journaled."""
    if not fill_id:
        return False
    ensure_journal_tables()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT entry_id FROM journal_fill_log WHERE fill_id = ?", (fill_id,)
        ).fetchone()
    return row is not None


def log_fill(
    fill_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    timestamp: datetime | str | None = None,
    source: str = "paper",
    note: str | None = None,
    context: str = "",
    tags: list[str] | None = None,
) -> Optional[str]:
    """Journal one fill.

    - A buy closes the oldest open *sell* (short) entry for the symbol and
      source; otherwise it opens a new long entry.
    - A sell closes the oldest open *buy* entry; otherwise it opens a short.

    Returns the affected journal entry id, or ``None`` when the fill was
    already logged (dedupe by ``fill_id``).
    """
    if source not in JOURNAL_SOURCES:
        source = "manual"
    if not symbol or qty <= 0 or price <= 0:
        return None
    if fill_id and already_logged(fill_id):
        return None

    ensure_journal_tables()
    sym = symbol.upper()
    side = "sell" if str(side).lower().startswith("sell") else "buy"
    when = _iso(timestamp)
    now = datetime.now(timezone.utc).isoformat()
    opposite = "sell" if side == "buy" else "buy"
    entry_id = str(uuid4())

    # Claim the fill id up front so concurrent writers can't double-apply it.
    if fill_id:
        with get_connection() as conn:
            try:
                cur = conn.cursor()
                cur.execute(
                    "INSERT OR IGNORE INTO journal_fill_log (fill_id, entry_id, source, applied_at) VALUES (?, ?, ?, ?)",
                    (fill_id, entry_id, source, now),
                )
                conn.commit()
                if cur.rowcount == 0:
                    return None
            except Exception:
                return None

    with get_connection() as conn:
        cur = conn.cursor()
        open_row = conn.execute(
            """SELECT id, quantity, entry_price FROM journal_entries
               WHERE symbol = ? AND side = ? AND status = 'open' AND source = ?
               ORDER BY entry_time ASC LIMIT 1""",
            (sym, opposite, source),
        ).fetchone()

        if open_row:
            entry_qty = float(open_row["quantity"])
            closed_qty = min(entry_qty, float(qty))
            remaining = entry_qty - closed_qty
            entry_price = float(open_row["entry_price"])
            if side == "sell":  # closing a long
                pnl = (price - entry_price) * closed_qty
            else:  # covering a short
                pnl = (entry_price - price) * closed_qty
            notional = entry_price * closed_qty
            pnl_pct = (pnl / notional * 100.0) if notional else 0.0

            if remaining > 1e-9:
                # Partial exit: shrink the open entry, keep it working.
                cur.execute(
                    "UPDATE journal_entries SET quantity = ?, updated_at = ? WHERE id = ?",
                    (remaining, now, open_row["id"]),
                )
                if fill_id:
                    cur.execute(
                        "UPDATE journal_fill_log SET entry_id = ? WHERE fill_id = ?",
                        (open_row["id"], fill_id),
                    )
                conn.commit()
                return open_row["id"]

            cur.execute(
                """UPDATE journal_entries
                   SET exit_price = ?, exit_time = ?, exit_context = ?, pnl = ?, pnl_pct = ?,
                       status = 'closed', updated_at = ?
                   WHERE id = ?""",
                (
                    price,
                    when,
                    context or note or f"Auto-logged {source} exit",
                    pnl,
                    pnl_pct,
                    now,
                    open_row["id"],
                ),
            )
            if fill_id:
                cur.execute(
                    "UPDATE journal_fill_log SET entry_id = ? WHERE fill_id = ?",
                    (open_row["id"], fill_id),
                )
            conn.commit()
            return open_row["id"]

        # No opposite entry — open a new one for this fill.
        label = note or f"Auto-logged {source} {side} {qty:g} {sym} @ {price:g}"
        all_tags = sorted({*(tags or []), "auto", source})
        try:
            cur.execute(
                """INSERT INTO journal_entries
                   (id, symbol, side, quantity, entry_price, entry_time, hypothesis,
                    entry_context, tags, status, source, fill_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
                (
                    entry_id, sym, side, float(qty), float(price), when, label,
                    context, json.dumps(all_tags), source, fill_id or None, now, now,
                ),
            )
            conn.commit()
        except Exception:
            # Unique fill_id race — another writer got there first.
            return None
        return entry_id


def stats_for_source(source: Optional[str] = None) -> dict:
    """Aggregated journal stats, optionally scoped to one source."""
    ensure_journal_tables()
    where = ""
    params: tuple = ()
    if source and source != "all":
        where = " WHERE source = ?"
        params = (source,)
    with get_connection() as conn:
        row = conn.execute(
            f"""SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'closed' AND pnl > 0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) AS closed,
                       COALESCE(SUM(CASE WHEN status = 'closed' THEN pnl ELSE 0 END), 0) AS pnl
                FROM journal_entries{where}""",
            params,
        ).fetchone()
    closed = int(row["closed"] or 0)
    wins = int(row["wins"] or 0)
    return {
        "total_trades": int(row["total"] or 0),
        "closed_trades": closed,
        "winning_trades": wins,
        "win_rate": (wins / closed * 100.0) if closed else 0.0,
        "total_pnl": float(row["pnl"] or 0.0),
    }
