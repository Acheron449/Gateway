from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


DB_PATH = Path(__file__).resolve().parents[3] / "quant_app.db"


@contextmanager
def get_connection():
    connection = sqlite3.connect(DB_PATH)
    try:
        yield connection
    finally:
        connection.close()


def init_db():
    """Create necessary tables for simulated orders, backtest runs, and paper portfolio if they don't exist."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                symbol TEXT,
                quantity REAL,
                avg_price REAL,
                status TEXT,
                provider TEXT,
                created_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS backtests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_ts TEXT,
                end_ts TEXT,
                initial_capital REAL,
                final_capital REAL,
                trades_count INTEGER
            )
            """
        )
        cur.execute(
            """
           CREATE TABLE IF NOT EXISTS backtest_jobs (
              id TEXT PRIMARY KEY,
              status TEXT NOT NULL DEFAULT 'queued',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              backtest_id INTEGER,
              payload TEXT,
              result TEXT,
              error TEXT
           )
           """
        )
        cur.execute(
            """
           CREATE TABLE IF NOT EXISTS trades (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              backtest_id INTEGER,
              signal_time TEXT,
              symbol TEXT,
              direction TEXT,
              confidence REAL,
              entry_price REAL,
              exit_price REAL,
              pnl_pct REAL,
              outcome TEXT,
              FOREIGN KEY(backtest_id) REFERENCES backtests(id)
           )
           """
        )
        # Paper portfolio tables (Phase 4)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolios (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                cash REAL NOT NULL DEFAULT 0,
                equity REAL NOT NULL DEFAULT 0,
                buying_power REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                avg_cost REAL NOT NULL DEFAULT 0,
                market_value REAL NOT NULL DEFAULT 0,
                unrealized_pnl REAL NOT NULL DEFAULT 0,
                realized_pnl REAL NOT NULL DEFAULT 0,
                FOREIGN KEY(portfolio_id) REFERENCES portfolios(id),
                UNIQUE(portfolio_id, instrument_id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_orders (
                id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                strategy_version_id TEXT,
                instrument_id TEXT NOT NULL,
                side TEXT NOT NULL,
                type TEXT NOT NULL,
                qty REAL NOT NULL,
                limit_price REAL,
                stop_price REAL,
                status TEXT NOT NULL DEFAULT 'pending_new',
                filled_qty REAL NOT NULL DEFAULT 0,
                avg_fill_price REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                instrument_id TEXT NOT NULL,
                side TEXT NOT NULL,
                qty REAL NOT NULL,
                price REAL NOT NULL,
                commission REAL NOT NULL DEFAULT 0,
                timestamp TEXT NOT NULL,
                liquidity TEXT,
                FOREIGN KEY(order_id) REFERENCES paper_orders(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS cash_ledger (
                id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                amount REAL NOT NULL,
                type TEXT NOT NULL,
                ref_id TEXT,
                ref_type TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_data TEXT NOT NULL,
                sequence_num INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY(portfolio_id) REFERENCES portfolios(id)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_portfolio_events_portfolio_id ON portfolio_events(portfolio_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_portfolio_events_sequence ON portfolio_events(portfolio_id, sequence_num)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_positions_portfolio_id ON positions(portfolio_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_paper_orders_portfolio_id ON paper_orders(portfolio_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_cash_ledger_portfolio_id ON cash_ledger(portfolio_id)
            """
        )
        conn.commit()


def insert_order(order_id: str, symbol: str, quantity: float, avg_price: float, status: str, provider: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO orders (order_id, symbol, quantity, avg_price, status, provider, created_at) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (order_id, symbol, quantity, avg_price, status, provider),
        )
        conn.commit()


def insert_backtest(start_ts: str, end_ts: str, initial_capital: float, final_capital: float, trades_count: int) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO backtests (start_ts, end_ts, initial_capital, final_capital, trades_count) VALUES (?, ?, ?, ?, ?)",
            (start_ts, end_ts, initial_capital, final_capital, trades_count),
        )
        conn.commit()
        return cur.lastrowid


def insert_trade(backtest_id: int, signal_time: str, symbol: str, direction: str, confidence: float, entry_price: float, exit_price: float, pnl_pct: float, outcome: str):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO trades (backtest_id, signal_time, symbol, direction, confidence, entry_price, exit_price, pnl_pct, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (backtest_id, signal_time, symbol, direction, confidence, entry_price, exit_price, pnl_pct, outcome),
        )
        conn.commit()


def create_backtest_job(job_id: str | None = None, payload: dict | None = None) -> str:
    init_db()
    created = job_id or str(uuid4())
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO backtest_jobs (id, status, created_at, updated_at, payload) VALUES (?, ?, ?, ?, ?)",
            (created, 'queued', now, now, json.dumps(payload or {})),
        )
        conn.commit()
    return created


def update_backtest_job(job_id: str, *, status: str | None = None, started_at: str | None = None, finished_at: str | None = None, backtest_id: int | None = None, result: dict | str | None = None, error: str | None = None) -> None:
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    payload = {
        'status': status,
        'updated_at': now,
        'started_at': started_at,
        'finished_at': finished_at,
        'backtest_id': backtest_id,
        'result': json.dumps(result) if result is not None and not isinstance(result, str) else result,
        'error': error,
    }
    # Whitelist of allowed column names to prevent SQL injection
    ALLOWED_COLUMNS = {'status', 'updated_at', 'started_at', 'finished_at', 'backtest_id', 'result', 'error', 'payload'}
    assignments = []
    values = []
    for key, value in payload.items():
        if value is None:
            continue
        if key not in ALLOWED_COLUMNS:
            continue  # Skip unknown columns
        assignments.append(f"{key} = ?")
        values.append(value)
    if not assignments:
        return
    values.append(job_id)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE backtest_jobs SET {', '.join(assignments)} WHERE id = ?", tuple(values))
        conn.commit()


def get_backtest_job(job_id: str) -> dict | None:
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM backtest_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        payload = dict(row)
        if payload.get('payload'):
            try:
                payload['payload'] = json.loads(payload['payload'])
            except Exception:
                pass
        if payload.get('result'):
            try:
                payload['result'] = json.loads(payload['result'])
            except Exception:
                pass
        return payload


def list_backtest_jobs(limit: int = 50) -> list[dict]:
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM backtest_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        if item.get('payload'):
            try:
                item['payload'] = json.loads(item['payload'])
            except Exception:
                pass
        if item.get('result'):
            try:
                item['result'] = json.loads(item['result'])
            except Exception:
                pass
        out.append(item)
    return out


# Paper portfolio database operations (Phase 4)
def create_portfolio(portfolio_id: str, user_id: str, initial_cash: float = 100000.0) -> dict:
    """Create a new paper portfolio with initial cash."""
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO portfolios (id, user_id, cash, equity, buying_power, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (portfolio_id, user_id, initial_cash, initial_cash, initial_cash, now, now),
        )
        # Add initial cash ledger entry
        cur.execute(
            """INSERT INTO cash_ledger (id, portfolio_id, amount, type, ref_id, ref_type, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), portfolio_id, initial_cash, 'deposit', None, None, now),
        )
        conn.commit()
    return get_portfolio(portfolio_id)


def get_portfolio(portfolio_id: str) -> dict | None:
    """Get portfolio with positions, open orders, and recent fills."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        portfolio_row = conn.execute("SELECT * FROM portfolios WHERE id = ?", (portfolio_id,)).fetchone()
        if not portfolio_row:
            return None
        portfolio = dict(portfolio_row)
        
        # Get positions
        positions = conn.execute(
            "SELECT * FROM positions WHERE portfolio_id = ?", (portfolio_id,)
        ).fetchall()
        portfolio['positions'] = [dict(p) for p in positions]
        
        # Get open orders
        open_orders = conn.execute(
            """SELECT * FROM paper_orders WHERE portfolio_id = ? 
               AND status IN ('pending_new', 'accepted', 'partially_filled')
               ORDER BY created_at DESC""",
            (portfolio_id,)
        ).fetchall()
        portfolio['open_orders'] = [dict(o) for o in open_orders]
        
        # Get recent fills (last 50)
        recent_fills = conn.execute(
            """SELECT f.* FROM fills f
               JOIN paper_orders o ON f.order_id = o.id
               WHERE o.portfolio_id = ?
               ORDER BY f.timestamp DESC LIMIT 50""",
            (portfolio_id,)
        ).fetchall()
        portfolio['recent_fills'] = [dict(f) for f in recent_fills]
        
    return portfolio


def get_portfolio_history(portfolio_id: str, limit: int = 100) -> list[dict]:
    """Get portfolio equity curve and cash flows from cash_ledger."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM cash_ledger WHERE portfolio_id = ? ORDER BY timestamp DESC LIMIT ?""",
            (portfolio_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def insert_paper_order(
    order_id: str, portfolio_id: str, strategy_version_id: str | None,
    instrument_id: str, side: str, order_type: str, qty: float,
    limit_price: float | None, stop_price: float | None
) -> None:
    """Insert a new paper order."""
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO paper_orders (id, portfolio_id, strategy_version_id, instrument_id, side, type, qty, 
               limit_price, stop_price, status, filled_qty, avg_fill_price, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending_new', 0, NULL, ?, ?)""",
            (order_id, portfolio_id, strategy_version_id, instrument_id, side, order_type, qty,
             limit_price, stop_price, now, now),
        )
        conn.commit()


def update_paper_order(order_id: str, **updates) -> None:
    """Update a paper order (status, filled_qty, avg_fill_price, etc.)."""
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    updates['updated_at'] = now
    # Whitelist of allowed column names to prevent SQL injection
    ALLOWED_COLUMNS = {'status', 'filled_qty', 'avg_fill_price', 'updated_at', 'strategy_version_id', 'limit_price', 'stop_price'}
    with get_connection() as conn:
        cur = conn.cursor()
        assignments = []
        values = []
        for k, v in updates.items():
            if k not in ALLOWED_COLUMNS:
                continue
            assignments.append(f"{k} = ?")
            values.append(v)
        if not assignments:
            return
        values.append(order_id)
        cur.execute(f"UPDATE paper_orders SET {', '.join(assignments)} WHERE id = ?", values)
        conn.commit()


def insert_fill(fill_id: str, order_id: str, instrument_id: str, side: str,
                qty: float, price: float, commission: float, timestamp: str, liquidity: str | None) -> None:
    """Insert a fill record."""
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO fills (id, order_id, instrument_id, side, qty, price, commission, timestamp, liquidity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (fill_id, order_id, instrument_id, side, qty, price, commission, timestamp, liquidity),
        )
        conn.commit()


def update_position(portfolio_id: str, instrument_id: str, quantity: float, avg_cost: float,
                    market_value: float, unrealized_pnl: float, realized_pnl: float) -> None:
    """Upsert a position."""
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO positions (id, portfolio_id, instrument_id, quantity, avg_cost, market_value, unrealized_pnl, realized_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(portfolio_id, instrument_id) DO UPDATE SET
                   quantity = excluded.quantity,
                   avg_cost = excluded.avg_cost,
                   market_value = excluded.market_value,
                   unrealized_pnl = excluded.unrealized_pnl,
                   realized_pnl = excluded.realized_pnl""",
            (f"{portfolio_id}_{instrument_id}", portfolio_id, instrument_id, quantity, avg_cost,
             market_value, unrealized_pnl, realized_pnl),
        )
        conn.commit()


def update_portfolio_cash(portfolio_id: str, cash: float, equity: float, buying_power: float) -> None:
    """Update portfolio cash, equity, and buying power."""
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE portfolios SET cash = ?, equity = ?, buying_power = ?, updated_at = ? WHERE id = ?",
            (cash, equity, buying_power, now, portfolio_id),
        )
        conn.commit()


def insert_cash_ledger(portfolio_id: str, amount: float, type_: str, ref_id: str | None, ref_type: str | None) -> None:
    """Insert a cash ledger entry."""
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO cash_ledger (id, portfolio_id, amount, type, ref_id, ref_type, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid4()), portfolio_id, amount, type_, ref_id, ref_type, now),
        )
        conn.commit()


def append_portfolio_event(portfolio_id: str, event_type: str, event_data: dict, sequence_num: int) -> None:
    """Append an event to the portfolio event log for event sourcing."""
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    import json
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO portfolio_events (portfolio_id, event_type, event_data, sequence_num, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (portfolio_id, event_type, json.dumps(event_data), sequence_num, now),
        )
        conn.commit()


def get_portfolio_events(portfolio_id: str, after_sequence: int = 0) -> list[dict]:
    """Get portfolio events for replay."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM portfolio_events WHERE portfolio_id = ? AND sequence_num > ?
               ORDER BY sequence_num ASC""",
            (portfolio_id, after_sequence)
        ).fetchall()
    import json
    return [dict(r) | {'event_data': json.loads(r['event_data'])} for r in rows]