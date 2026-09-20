from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.models import StrategySpec, StrategyVersion, StrategyStatus, Timeframe, RuleType
from app.services.database import get_connection, init_db
from uuid import uuid4
from datetime import datetime, timezone
import json


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

def _get_strategy_table():
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                current_version INTEGER NOT NULL DEFAULT 1,
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS strategy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                spec TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(strategy_id) REFERENCES strategies(id),
                UNIQUE(strategy_id, version)
            )
        """)
        conn.commit()


def _load_strategy(strategy_id: str) -> dict | None:
    init_db()
    with get_connection() as conn:
        conn.row_factory = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone().__class__
        row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not row:
        return None
    return dict(row)


# --- Routes ---

@router.post("", response_model=StrategyResponse, status_code=201)
async def create_strategy(request: StrategyCreateRequest) -> StrategyResponse:
    """Create a new strategy with initial version."""
    _get_strategy_table()
    
    strategy_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Create strategy spec from request
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
            """INSERT INTO strategies (id, name, description, status, current_version, tags, created_at, updated_at)
               VALUES (?, ?, ?, 'draft', 1, ?, ?, ?)""",
            (strategy_id, request.name, request.description, json.dumps(request.tags), now, now),
        )
        cur.execute(
            """INSERT INTO strategy_versions (strategy_id, version, spec, created_at)
               VALUES (?, ?, ?, ?)""",
            (strategy_id, 1, json.dumps(spec.model_dump(mode="json")), now),
        )
        conn.commit()
    
    return StrategyResponse(
        id=strategy_id,
        name=request.name,
        description=request.description,
        status=StrategyStatus.DRAFT,
        version=1,
        universe=request.universe,
        timeframe=request.timeframe.value,
        tags=request.tags,
        created_at=now,
        updated_at=now,
    )


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(
    status: StrategyStatus | None = Query(None),
    tag: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[StrategyResponse]:
    """List strategies with optional filtering."""
    _get_strategy_table()
    
    query = "SELECT * FROM strategies WHERE 1=1"
    params = []
    
    if status:
        query += " AND status = ?"
        params.append(status.value)
    if tag:
        query += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    
    query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    with get_connection() as conn:
        conn.row_factory = conn.execute(query, params).fetchone().__class__
        rows = conn.execute(query, params).fetchall()
    
    return [
        StrategyResponse(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            status=StrategyStatus(row["status"]),
            version=row["current_version"],
            universe=json.loads(row.get("universe", "[]")),
            timeframe=row.get("timeframe", "1h"),
            tags=json.loads(row["tags"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str) -> StrategyResponse:
    """Get a strategy by ID."""
    _get_strategy_table()
    
    strategy = _load_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    return StrategyResponse(
        id=strategy["id"],
        name=strategy["name"],
        description=strategy["description"],
        status=StrategyStatus(strategy["status"]),
        version=strategy["current_version"],
        universe=json.loads(strategy.get("universe", "[]")),
        timeframe=strategy.get("timeframe", "1h"),
        tags=json.loads(strategy["tags"]),
        created_at=strategy["created_at"],
        updated_at=strategy["updated_at"],
    )


@router.get("/{strategy_id}/versions", response_model=list[StrategyVersionResponse])
async def list_strategy_versions(strategy_id: str) -> list[StrategyVersionResponse]:
    """List all versions of a strategy."""
    _get_strategy_table()
    
    strategy = _load_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    with get_connection() as conn:
        conn.row_factory = conn.execute("SELECT * FROM strategy_versions WHERE strategy_id = ? ORDER BY version DESC", (strategy_id,)).fetchone().__class__
        rows = conn.execute("SELECT * FROM strategy_versions WHERE strategy_id = ? ORDER BY version DESC", (strategy_id,)).fetchall()
    
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
async def get_strategy_version(strategy_id: str, version: int) -> StrategyVersionResponse:
    """Get a specific version of a strategy."""
    _get_strategy_table()
    
    strategy = _load_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    with get_connection() as conn:
        conn.row_factory = conn.execute("SELECT * FROM strategy_versions WHERE strategy_id = ? AND version = ?", (strategy_id, version)).fetchone().__class__
        row = conn.execute("SELECT * FROM strategy_versions WHERE strategy_id = ? AND version = ?", (strategy_id, version)).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    
    return StrategyVersionResponse(
        strategy_id=row["strategy_id"],
        version=row["version"],
        spec=json.loads(row["spec"]),
        created_at=row["created_at"],
    )


@router.post("/{strategy_id}/versions", response_model=StrategyVersionResponse, status_code=201)
async def create_strategy_version(strategy_id: str, spec: StrategySpec) -> StrategyVersionResponse:
    """Create a new version of a strategy."""
    _get_strategy_table()
    
    strategy = _load_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    new_version = strategy["current_version"] + 1
    now = datetime.now(timezone.utc).isoformat()
    
    # Validate the spec matches the strategy
    if spec.strategy_id != strategy_id:
        spec = spec.model_copy(update={"strategy_id": strategy_id})
    if spec.version != new_version:
        spec = spec.model_copy(update={"version": new_version})
    
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE strategies SET current_version = ?, updated_at = ? WHERE id = ?""",
            (new_version, now, strategy_id),
        )
        cur.execute(
            """INSERT INTO strategy_versions (strategy_id, version, spec, created_at)
               VALUES (?, ?, ?, ?)""",
            (strategy_id, new_version, json.dumps(spec.model_dump(mode="json")), now),
        )
        conn.commit()
    
    return StrategyVersionResponse(
        strategy_id=strategy_id,
        version=new_version,
        spec=spec.model_dump(mode="json"),
        created_at=now,
    )


@router.patch("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(strategy_id: str, request: StrategyUpdateRequest) -> StrategyResponse:
    """Update strategy metadata."""
    _get_strategy_table()
    
    strategy = _load_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    now = datetime.now(timezone.utc).isoformat()
    updates = []
    params = []
    
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
        params.append(now)
        params.append(strategy_id)
        
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE strategies SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
    
    # Reload
    updated = _load_strategy(strategy_id)
    
    return StrategyResponse(
        id=updated["id"],
        name=updated["name"],
        description=updated["description"],
        status=StrategyStatus(updated["status"]),
        version=updated["current_version"],
        universe=json.loads(updated.get("universe", "[]")),
        timeframe=updated.get("timeframe", "1h"),
        tags=json.loads(updated["tags"]),
        created_at=updated["created_at"],
        updated_at=updated["updated_at"],
    )


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(strategy_id: str):
    """Delete a strategy and all its versions."""
    _get_strategy_table()
    
    strategy = _load_strategy(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM strategy_versions WHERE strategy_id = ?", (strategy_id,))
        cur.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
        conn.commit()