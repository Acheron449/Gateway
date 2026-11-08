"""Strategy Studio: typed strategy specs, immutable versions and ownership.

Every route derives its owner from the verified principal (NFR-6). Reads and
writes are scoped by ``owner_id``: another account's strategy, version or run id
is indistinguishable from a missing one (404), and rows created before ownership
existed keep a NULL owner and therefore stay invisible (DR-6/DR-7).

Backtests are not executed here. ``POST /backtest/run`` owns reproducible runs
and receipts; this module stores only specs and their versions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.models import (
    EntryRule,
    EventRule,
    ExitRule,
    InvalidationRule,
    SessionRule,
    SizingRule,
    StrategySpec,
    StrategyStatus,
    Timeframe,
    compute_strategy_content_hash,
)
from app.services.database import get_connection, init_db


router = APIRouter(prefix="/strategies", tags=["strategies"])


# --- Request/Response Models ---

class StrategyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    universe: list[str] = Field(default_factory=list)
    timeframe: Timeframe = Timeframe.H1
    entry_rules: list[dict] = Field(default_factory=list)
    exit_rules: list[dict] = Field(default_factory=list)
    sizing_rules: list[dict] = Field(default_factory=list)
    invalidation_rules: list[dict] = Field(default_factory=list)
    session_rules: list[dict] = Field(default_factory=list)
    event_rules: list[dict] = Field(default_factory=list)
    assumptions: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class StrategyUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    universe: list[str] | None = None
    timeframe: Timeframe | None = None
    entry_rules: list[dict] | None = None
    exit_rules: list[dict] | None = None
    sizing_rules: list[dict] | None = None
    invalidation_rules: list[dict] | None = None
    session_rules: list[dict] | None = None
    event_rules: list[dict] | None = None
    assumptions: dict | None = None
    tags: list[str] | None = None
    status: StrategyStatus | None = None


class StrategyResponse(BaseModel):
    id: str
    name: str
    description: str
    status: StrategyStatus
    version: int
    universe: list[str]
    timeframe: str
    tags: list[str]
    created_at: str
    updated_at: str


class StrategyVersionResponse(BaseModel):
    strategy_id: str
    version: int
    spec: dict
    created_at: str


# --- Database Helpers ---

def _get_strategy_table() -> None:
    """Create the strategy tables and migrate pre-ownership databases.

    ``owner_id`` is added by migration for databases created before ownership
    existed. Those legacy rows keep a NULL owner, so no account can list, read
    or delete them (DR-6/DR-7) until an operator assigns an owner explicitly.
    """
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                owner_id TEXT,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                current_version INTEGER NOT NULL DEFAULT 1,
                universe TEXT NOT NULL DEFAULT '[]',
                timeframe TEXT NOT NULL DEFAULT '1h',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        columns = {row[1] for row in cur.execute("PRAGMA table_info(strategies)").fetchall()}
        for column, ddl in (
            ("owner_id", "ALTER TABLE strategies ADD COLUMN owner_id TEXT"),
            ("universe", "ALTER TABLE strategies ADD COLUMN universe TEXT NOT NULL DEFAULT '[]'"),
            ("timeframe", "ALTER TABLE strategies ADD COLUMN timeframe TEXT NOT NULL DEFAULT '1h'"),
        ):
            if column not in columns:
                cur.execute(ddl)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_strategies_owner ON strategies(owner_id, updated_at DESC)"
        )
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                spec TEXT NOT NULL,
                created_at TEXT NOT NULL,
                content_hash TEXT,
                FOREIGN KEY(strategy_id) REFERENCES strategies(id),
                UNIQUE(strategy_id, version)
            )
        """)
        version_columns = {row[1] for row in cur.execute("PRAGMA table_info(strategy_versions)").fetchall()}
        if "content_hash" not in version_columns:
            cur.execute("ALTER TABLE strategy_versions ADD COLUMN content_hash TEXT")
        conn.commit()


def _load_strategy(strategy_id: str, owner_id: str) -> dict | None:
    """Load a strategy only when it belongs to ``owner_id``."""
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM strategies WHERE id = ? AND owner_id = ?",
            (strategy_id, owner_id),
        ).fetchone()
    return dict(row) if row else None


def _to_response(strategy: dict) -> StrategyResponse:
    return StrategyResponse(
        id=strategy["id"],
        name=strategy["name"],
        description=strategy["description"] or "",
        status=StrategyStatus(strategy["status"]),
        version=strategy["current_version"],
        universe=json.loads(strategy.get("universe") or "[]"),
        timeframe=strategy.get("timeframe") or "1h",
        tags=json.loads(strategy.get("tags") or "[]"),
        created_at=strategy["created_at"],
        updated_at=strategy["updated_at"],
    )


def _owned_strategy_or_404(strategy_id: str, owner_id: str) -> dict:
    strategy = _load_strategy(strategy_id, owner_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


# --- Routes ---

@router.post("", response_model=StrategyResponse, status_code=201)
async def create_strategy(request: StrategyCreateRequest, user: CurrentUser) -> StrategyResponse:
    """Create a new strategy owned by the signed-in account."""
    _get_strategy_table()

    strategy_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()

    spec = StrategySpec(
        strategy_id=strategy_id,
        version=1,
        name=request.name,
        description=request.description,
        universe=request.universe,
        timeframe=request.timeframe,
        entry_rules=[EntryRule(**r) for r in request.entry_rules],
        exit_rules=[ExitRule(**r) for r in request.exit_rules],
        sizing_rules=[SizingRule(**r) for r in request.sizing_rules],
        invalidation_rules=[InvalidationRule(**r) for r in request.invalidation_rules],
        session_rules=[SessionRule(**r) for r in request.session_rules],
        event_rules=[EventRule(**r) for r in request.event_rules],
        assumptions=request.assumptions,
        tags=request.tags,
    )

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO strategies (id, owner_id, name, description, status, current_version,
                                       universe, timeframe, tags, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'draft', 1, ?, ?, ?, ?, ?)""",
            (
                strategy_id,
                user.id,
                request.name,
                request.description,
                json.dumps(request.universe),
                request.timeframe.value,
                json.dumps(request.tags),
                now,
                now,
            ),
        )
        stored_spec = spec.model_dump(mode="json", exclude={"content_hash"})
        content_hash = compute_strategy_content_hash(spec)
        cur.execute(
            """INSERT INTO strategy_versions (strategy_id, version, spec, created_at, content_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (strategy_id, 1, json.dumps(stored_spec), now, content_hash),
        )
        conn.commit()

    created = _load_strategy(strategy_id, user.id)
    assert created is not None
    return _to_response(created)


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(
    user: CurrentUser,
    status: StrategyStatus | None = Query(None),
    tag: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[StrategyResponse]:
    """List the signed-in account's strategies with optional filtering."""
    _get_strategy_table()

    query = "SELECT * FROM strategies WHERE owner_id = ?"
    params: list[Any] = [user.id]

    if status:
        query += " AND status = ?"
        params.append(status.value)
    if tag:
        query += " AND tags LIKE ?"
        params.append(f"%{tag}%")

    query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [_to_response(dict(row)) for row in rows]


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str, user: CurrentUser) -> StrategyResponse:
    """Get one of the signed-in account's strategies by id."""
    _get_strategy_table()
    return _to_response(_owned_strategy_or_404(strategy_id, user.id))


@router.get("/{strategy_id}/versions", response_model=list[StrategyVersionResponse])
async def list_strategy_versions(strategy_id: str, user: CurrentUser) -> list[StrategyVersionResponse]:
    """List all versions of one of the signed-in account's strategies."""
    _get_strategy_table()
    _owned_strategy_or_404(strategy_id, user.id)

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM strategy_versions WHERE strategy_id = ? ORDER BY version DESC",
            (strategy_id,),
        ).fetchall()

    return [
        StrategyVersionResponse(
            strategy_id=row["strategy_id"],
            version=row["version"],
            spec=json.loads(row["spec"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]


@router.get("/{strategy_id}/versions/{version}", response_model=StrategyVersionResponse)
async def get_strategy_version(
    strategy_id: str, version: int, user: CurrentUser
) -> StrategyVersionResponse:
    """Get a specific version of one of the signed-in account's strategies."""
    _get_strategy_table()
    _owned_strategy_or_404(strategy_id, user.id)

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM strategy_versions WHERE strategy_id = ? AND version = ?",
            (strategy_id, version),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Version not found")

    return StrategyVersionResponse(
        strategy_id=row["strategy_id"],
        version=row["version"],
        spec=json.loads(row["spec"]),
        created_at=row["created_at"],
    )


@router.post("/{strategy_id}/versions", response_model=StrategyVersionResponse, status_code=201)
async def create_strategy_version(
    strategy_id: str, spec: StrategySpec, user: CurrentUser
) -> StrategyVersionResponse:
    """Append a new immutable version to one of the account's strategies."""
    _get_strategy_table()

    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            strategy_row = cur.execute(
                "SELECT * FROM strategies WHERE id = ? AND owner_id = ?",
                (strategy_id, user.id),
            ).fetchone()
            if strategy_row is None:
                conn.rollback()
                raise HTTPException(status_code=404, detail="Strategy not found")
            new_version = strategy_row["current_version"] + 1
            # Validate/canonicalize with the assigned identity and version.
            spec = spec.model_copy(
                update={"strategy_id": strategy_id, "version": new_version, "content_hash": None}
            )
            content_hash = compute_strategy_content_hash(spec)
            stored_spec = spec.model_dump(mode="json", exclude={"content_hash"})
            cur.execute(
                "UPDATE strategies SET current_version = ?, updated_at = ? WHERE id = ? AND owner_id = ?",
                (new_version, now, strategy_id, user.id),
            )
            cur.execute(
                """INSERT INTO strategy_versions (strategy_id, version, spec, created_at, content_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (strategy_id, new_version, json.dumps(stored_spec), now, content_hash),
            )
            conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        if "unique" in str(exc).lower() or "locked" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Strategy version allocation conflict") from exc
        raise

    return StrategyVersionResponse(
        strategy_id=strategy_id,
        version=new_version,
        spec=spec.model_dump(mode="json"),
        created_at=now,
    )


@router.patch("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: str, request: StrategyUpdateRequest, user: CurrentUser
) -> StrategyResponse:
    """Update metadata on one of the signed-in account's strategies."""
    _get_strategy_table()
    _owned_strategy_or_404(strategy_id, user.id)

    now = datetime.now(timezone.utc).isoformat()
    updates = []
    params: list[Any] = []

    for field, value in request.model_dump(exclude_unset=True).items():
        if field == "universe":
            updates.append("universe = ?")
            params.append(json.dumps(value))
        elif field == "tags":
            updates.append("tags = ?")
            params.append(json.dumps(value))
        elif field == "timeframe" and value:
            updates.append("timeframe = ?")
            params.append(value.value)
        elif field == "status" and value:
            updates.append("status = ?")
            params.append(value.value)
        else:
            updates.append(f"{field} = ?")
            params.append(value)

    if updates:
        updates.append("updated_at = ?")
        params.extend([now, strategy_id, user.id])

        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE strategies SET {', '.join(updates)} WHERE id = ? AND owner_id = ?",
                params,
            )
            conn.commit()

    updated = _load_strategy(strategy_id, user.id)
    assert updated is not None
    return _to_response(updated)


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: str, user: CurrentUser):
    """Delete one of the signed-in account's strategies and all its versions."""
    _get_strategy_table()
    _owned_strategy_or_404(strategy_id, user.id)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM strategy_versions WHERE strategy_id = ? AND strategy_id IN "
            "(SELECT id FROM strategies WHERE id = ? AND owner_id = ?)",
            (strategy_id, strategy_id, user.id),
        )
        cur.execute("DELETE FROM strategies WHERE id = ? AND owner_id = ?", (strategy_id, user.id))
        conn.commit()
