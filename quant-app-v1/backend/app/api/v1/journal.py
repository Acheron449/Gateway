from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.database import get_connection, init_db


router = APIRouter(prefix="/journal", tags=["journal"])


# --- Models ---

class JournalEntryCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=12)
    side: str = Field(pattern="^(buy|sell)$")
    quantity: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    hypothesis: str = Field(min_length=1)
    entry_context: str = ""
    tags: List[str] = Field(default_factory=list)


class JournalEntryUpdate(BaseModel):
    exit_price: Optional[float] = None
    exit_context: Optional[str] = None
    exit_time: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    lessons: Optional[str] = None
    tags: Optional[List[str]] = None


class JournalEntryResponse(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: Optional[float] = None
    entry_time: str
    exit_time: Optional[str] = None
    hypothesis: str
    entry_context: str
    exit_context: Optional[str] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    rating: Optional[int] = None
    lessons: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    status: str
    created_at: str
    updated_at: str


class JournalStatsResponse(BaseModel):
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    avg_hold_time: str


# --- Database Helpers ---

def _get_journal_table():
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
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
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_journal_symbol ON journal_entries(symbol)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_journal_status ON journal_entries(status)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_journal_created ON journal_entries(created_at)
        """)
        conn.commit()


def _row_to_entry(row) -> dict:
    import json
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "side": row["side"],
        "quantity": row["quantity"],
        "entry_price": row["entry_price"],
        "exit_price": row["exit_price"],
        "entry_time": row["entry_time"],
        "exit_time": row["exit_time"],
        "hypothesis": row["hypothesis"],
        "entry_context": row["entry_context"],
        "exit_context": row["exit_context"],
        "pnl": row["pnl"],
        "pnl_pct": row["pnl_pct"],
        "rating": row["rating"],
        "lessons": row["lessons"],
        "tags": json.loads(row["tags"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# --- Routes ---

@router.post("", response_model=JournalEntryResponse, status_code=201)
async def create_journal_entry(request: JournalEntryCreate) -> JournalEntryResponse:
    """Create a new trade journal entry."""
    _get_journal_table()
    
    entry_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO journal_entries 
               (id, symbol, side, quantity, entry_price, entry_time, hypothesis, entry_context, tags, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (entry_id, request.symbol.upper(), request.side.lower(), request.quantity,
             request.entry_price, now, request.hypothesis, request.entry_context,
             json.dumps(request.tags), now, now),
        )
        conn.commit()
    
    return JournalEntryResponse(
        id=entry_id,
        symbol=request.symbol.upper(),
        side=request.side.lower(),
        quantity=request.quantity,
        entry_price=request.entry_price,
        entry_time=now,
        hypothesis=request.hypothesis,
        entry_context=request.entry_context,
        tags=request.tags,
        status="open",
        created_at=now,
        updated_at=now,
    )


@router.get("", response_model=Dict[str, Any])
async def list_journal_entries(
    status: Optional[str] = Query(None, pattern="^(open|closed|all)$"),
    symbol: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """List journal entries with optional filtering."""
    _get_journal_table()
    
    query = "SELECT * FROM journal_entries WHERE 1=1"
    params = []
    
    if status and status != "all":
        query += " AND status = ?"
        params.append(status)
    if symbol:
        query += " AND symbol = ?"
        params.append(symbol.upper())
    if tag:
        query += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if start_date:
        query += " AND created_at >= ?"
        params.append(start_date)
    if end_date:
        query += " AND created_at <= ?"
        params.append(end_date)
    
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    with get_connection() as conn:
        conn.row_factory = conn.execute(query, params).fetchone().__class__
        rows = conn.execute(query, params).fetchall()
    
    entries = [_row_to_entry(row) for row in rows]
    
    return {"entries": entries}


@router.get("/stats", response_model=JournalStatsResponse)
async def get_journal_stats() -> JournalStatsResponse:
    """Get aggregated journal statistics."""
    _get_journal_table()
    
    with get_connection() as conn:
        # Total trades
        total = conn.execute("SELECT COUNT(*) as cnt FROM journal_entries").fetchone()["cnt"]
        
        # Closed trades
        closed = conn.execute("SELECT COUNT(*) as cnt FROM journal_entries WHERE status = 'closed'").fetchone()["cnt"]
        
        # Win/loss
        winning = conn.execute("SELECT COUNT(*) as cnt FROM journal_entries WHERE status = 'closed' AND pnl > 0").fetchone()["cnt"]
        losing = conn.execute("SELECT COUNT(*) as cnt FROM journal_entries WHERE status = 'closed' AND pnl <= 0").fetchone()["cnt"]
        
        # PnL stats
        total_pnl = conn.execute("SELECT COALESCE(SUM(pnl), 0) as sum FROM journal_entries WHERE status = 'closed'").fetchone()["sum"]
        avg_win = conn.execute("SELECT COALESCE(AVG(pnl), 0) as avg FROM journal_entries WHERE status = 'closed' AND pnl > 0").fetchone()["avg"]
        avg_loss = conn.execute("SELECT COALESCE(AVG(pnl), 0) as avg FROM journal_entries WHERE status = 'closed' AND pnl <= 0").fetchone()["avg"]
        
        # Hold time
        hold_time = conn.execute("""
            SELECT AVG(julianday(exit_time) - julianday(entry_time)) * 24 * 60 as avg_minutes
            FROM journal_entries WHERE status = 'closed' AND exit_time IS NOT NULL
        """).fetchone()["avg_minutes"] or 0
        
        win_rate = (winning / closed * 100) if closed > 0 else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")
        
        # Format avg hold time
        hours = int(hold_time // 60)
        minutes = int(hold_time % 60)
        hold_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        
        return JournalStatsResponse(
            total_trades=total,
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            total_pnl=total_pnl,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            avg_hold_time=hold_str,
        )


@router.get("/{entry_id}", response_model=JournalEntryResponse)
async def get_journal_entry(entry_id: str) -> JournalEntryResponse:
    """Get a single journal entry by ID."""
    _get_journal_table()
    
    with get_connection() as conn:
        conn.row_factory = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone().__class__
        row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    
    return JournalEntryResponse(**_row_to_entry(row))


@router.patch("/{entry_id}", response_model=JournalEntryResponse)
async def update_journal_entry(entry_id: str, request: JournalEntryUpdate) -> JournalEntryResponse:
    """Update a journal entry (close trade, add exit details, etc.)."""
    _get_journal_table()
    
    # Check exists
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Journal entry not found")
    
    updates = []
    params = []
    now = datetime.now(timezone.utc).isoformat()
    
    if request.exit_price is not None:
        updates.append("exit_price = ?")
        params.append(request.exit_price)
    if request.exit_context is not None:
        updates.append("exit_context = ?")
        params.append(request.exit_context)
    if request.exit_time is not None:
        updates.append("exit_time = ?")
        params.append(request.exit_time)
    if request.rating is not None:
        updates.append("rating = ?")
        params.append(request.rating)
    if request.lessons is not None:
        updates.append("lessons = ?")
        params.append(request.lessons)
    if request.tags is not None:
        import json
        updates.append("tags = ?")
        params.append(json.dumps(request.tags))
    
    # If closing the trade, calculate PnL
    if request.exit_price is not None and row["status"] == "open":
        entry_price = row["entry_price"]
        quantity = row["quantity"]
        side = row["side"]
        exit_price = request.exit_price
        
        if side == "buy":
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity
        
        pnl_pct = (pnl / (entry_price * quantity)) * 100 if entry_price * quantity != 0 else 0
        
        updates.append("pnl = ?")
        params.append(pnl)
        updates.append("pnl_pct = ?")
        params.append(pnl_pct)
        updates.append("status = ?")
        params.append("closed")
        if not request.exit_time:
            updates.append("exit_time = ?")
            params.append(datetime.now(timezone.utc).isoformat())
    
    if updates:
        updates.append("updated_at = ?")
        params.append(now)
        params.append(entry_id)
        
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(f"UPDATE journal_entries SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
    
    # Return updated
    with get_connection() as conn:
        conn.row_factory = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone().__class__
        row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    
    return JournalEntryResponse(**_row_to_entry(row))


@router.post("/{entry_id}/close", response_model=JournalEntryResponse)
async def close_trade(entry_id: str, request: JournalEntryUpdate) -> JournalEntryResponse:
    """Close a trade with exit details."""
    return await update_journal_entry(entry_id, request)


@router.delete("/{entry_id}", status_code=204)
async def delete_journal_entry(entry_id: str):
    """Delete a journal entry."""
    _get_journal_table()
    
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Journal entry not found")
        conn.commit()