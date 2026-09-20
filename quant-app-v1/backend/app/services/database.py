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
        # Economic events table (Phase 2)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS economic_events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                country TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                importance TEXT NOT NULL DEFAULT 'medium',
                scheduled_at TEXT NOT NULL,
                actual REAL,
                forecast REAL,
                prior REAL,
                revisions TEXT,  -- JSON array
                related_symbols TEXT,  -- JSON array
                provider_version TEXT NOT NULL,
                source TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                data_time TEXT,
                coverage TEXT,
                delay_seconds INTEGER,
                entitlement TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_economic_events_scheduled ON economic_events(scheduled_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_economic_events_importance ON economic_events(importance)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_economic_events_country ON economic_events(country)
            """
        )

        # News items table (Phase 2)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS news_items (
                id TEXT PRIMARY KEY,
                headline TEXT NOT NULL,
                url TEXT,
                source TEXT NOT NULL,
                published_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                categories TEXT,  -- JSON array
                related_symbols TEXT,  -- JSON array
                sentiment_score REAL,
                provider_version TEXT NOT NULL,
                coverage TEXT,
                delay_seconds INTEGER,
                entitlement TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_news_items_published ON news_items(published_at)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_news_items_source ON news_items(source)
            """
        )

        # Event/News snapshots for backtest reproducibility (Phase 2)
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS event_snapshots (
                id TEXT PRIMARY KEY,
                snapshot_type TEXT NOT NULL,  -- 'economic_event' | 'news'
                event_id TEXT NOT NULL,
                snapshot_data TEXT NOT NULL,  -- JSON serialized event/news
                provider_version TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                UNIQUE(event_id, provider_version)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_snapshots_type ON event_snapshots(snapshot_type)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_snapshots_captured ON event_snapshots(captured_at)
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


# --- Event/News Snapshots for Backtest Reproducibility (Phase 2) ---

def store_event_snapshot(
    event_id: str,
    snapshot_type: str,  # 'economic_event' | 'news'
    event_data: dict,
    provider_version: str,
) -> str:
    """Store an immutable snapshot of an event or news item for backtest reproducibility."""
    init_db()
    snapshot_id = str(uuid4())
    now = __import__('datetime').datetime.utcnow().isoformat()
    import json
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO event_snapshots (id, snapshot_type, event_id, snapshot_data, provider_version, captured_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (snapshot_id, snapshot_type, event_id, json.dumps(event_data), provider_version, now),
        )
        conn.commit()
    return snapshot_id


def get_event_snapshot(event_id: str, provider_version: str) -> dict | None:
    """Retrieve an event/news snapshot by event_id and provider_version."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """SELECT * FROM event_snapshots WHERE event_id = ? AND provider_version = ?""",
            (event_id, provider_version)
        ).fetchone()
    if not row:
        return None
    import json
    data = dict(row)
    data['snapshot_data'] = json.loads(data['snapshot_data'])
    return data


def get_event_snapshots_by_type(snapshot_type: str, limit: int = 100) -> list[dict]:
    """Get recent event snapshots of a specific type."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM event_snapshots WHERE snapshot_type = ? ORDER BY captured_at DESC LIMIT ?""",
            (snapshot_type, limit)
        ).fetchall()
    import json
    return [dict(r) | {'snapshot_data': json.loads(r['snapshot_data'])} for r in rows]


# --- Economic Events (Phase 2) ---

def insert_economic_event(event: dict) -> None:
    """Insert or replace an economic event."""
    init_db()
    import json
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO economic_events 
               (id, title, country, currency, importance, scheduled_at, actual, forecast, prior,
                revisions, related_symbols, provider_version, source, fetched_at, data_time,
                coverage, delay_seconds, entitlement)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.get('id'),
                event.get('title'),
                event.get('country'),
                event.get('currency'),
                event.get('importance'),
                event.get('scheduled_at'),
                event.get('actual'),
                event.get('forecast'),
                event.get('prior'),
                json.dumps(event.get('revisions', [])),
                json.dumps(event.get('related_symbols', [])),
                event.get('provider_version'),
                event.get('source'),
                event.get('fetched_at'),
                event.get('data_time'),
                event.get('coverage'),
                event.get('delay_seconds'),
                event.get('entitlement'),
            ),
        )
        conn.commit()


def get_economic_events(
    since: str | None = None,
    until: str | None = None,
    countries: list[str] | None = None,
    currencies: list[str] | None = None,
    importance: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query economic events with filters."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM economic_events WHERE 1=1"
        params = []
        
        if since:
            query += " AND scheduled_at >= ?"
            params.append(since)
        if until:
            query += " AND scheduled_at <= ?"
            params.append(until)
        if countries:
            placeholders = ','.join(['?'] * len(countries))
            query += f" AND country IN ({placeholders})"
            params.extend(countries)
        if currencies:
            placeholders = ','.join(['?'] * len(currencies))
            query += f" AND currency IN ({placeholders})"
            params.extend(currencies)
        if importance:
            query += " AND importance = ?"
            params.append(importance)
        
        query += " ORDER BY scheduled_at ASC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
    
    import json
    result = []
    for row in rows:
        data = dict(row)
        data['revisions'] = json.loads(data['revisions']) if data.get('revisions') else []
        data['related_symbols'] = json.loads(data['related_symbols']) if data.get('related_symbols') else []
        result.append(data)
    return result


def get_economic_event(event_id: str) -> dict | None:
    """Get a single economic event by ID."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM economic_events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        return None
    import json
    data = dict(row)
    data['revisions'] = json.loads(data['revisions']) if data.get('revisions') else []
    data['related_symbols'] = json.loads(data['related_symbols']) if data.get('related_symbols') else []
    return data


# --- News Items (Phase 2) ---

def insert_news_item(item: dict) -> None:
    """Insert or replace a news item."""
    init_db()
    import json
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT OR REPLACE INTO news_items
               (id, headline, url, source, published_at, fetched_at, categories,
                related_symbols, sentiment_score, provider_version, coverage, delay_seconds, entitlement)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.get('id'),
                item.get('headline'),
                item.get('url'),
                item.get('source'),
                item.get('published_at'),
                item.get('fetched_at'),
                json.dumps(item.get('categories', [])),
                json.dumps(item.get('related_symbols', [])),
                item.get('sentiment_score'),
                item.get('provider_version'),
                item.get('coverage'),
                item.get('delay_seconds'),
                item.get('entitlement'),
            ),
        )
        conn.commit()


def get_news_items(
    since: str | None = None,
    symbols: list[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    """Query news items with filters."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM news_items WHERE 1=1"
        params = []
        
        if since:
            query += " AND published_at >= ?"
            params.append(since)
        if symbols:
            # Search in related_symbols JSON array
            # For simplicity, we'll filter in Python after query
            pass
        
        query += " ORDER BY published_at DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
    
    import json
    result = []
    for row in rows:
        data = dict(row)
        data['categories'] = json.loads(data['categories']) if data.get('categories') else []
        data['related_symbols'] = json.loads(data['related_symbols']) if data.get('related_symbols') else []
        
        # Filter by symbols if provided
        if symbols:
            if not any(s in data.get('related_symbols', []) for s in symbols):
                continue
        
        result.append(data)
    return result


def get_news_item(news_id: str) -> dict | None:
    """Get a single news item by ID."""
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM news_items WHERE id = ?", (news_id,)).fetchone()
    if not row:
        return None
    import json
    data = dict(row)
    data['categories'] = json.loads(data['categories']) if data.get('categories') else []
    data['related_symbols'] = json.loads(data['related_symbols']) if data.get('related_symbols') else []
    return data


# --- Phase 1.4 User & Preference helpers ---

def create_user(user_id: str, email: str, hashed_password: str, name: str | None = None) -> None:
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, email, name, hashed_password, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, name, hashed_password, now),
        )
        conn.commit()


def get_user_by_email(email: str) -> dict | None:
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_watchlist(wl_id: str, user_id: str, name: str, symbols: list[str]) -> None:
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO watchlists (id, user_id, name, symbols, created_at) VALUES (?, ?, ?, ?, ?)",
            (wl_id, user_id, name, json.dumps(symbols), now),
        )
        conn.commit()


def list_watchlists(user_id: str) -> list[dict]:
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM watchlists WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item['symbols'] = json.loads(item['symbols']) if item.get('symbols') else []
        out.append(item)
    return out


def update_watchlist(wl_id: str, *, name: str | None = None, symbols: list[str] | None = None) -> None:
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        if name is not None:
            cur.execute("UPDATE watchlists SET name = ?, created_at = ? WHERE id = ?", (name, now, wl_id))
        if symbols is not None:
            cur.execute("UPDATE watchlists SET symbols = ?, created_at = ? WHERE id = ?", (json.dumps(symbols), now, wl_id))
        conn.commit()


def delete_watchlist(wl_id: str) -> None:
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM watchlists WHERE id = ?", (wl_id,))
        conn.commit()


def upsert_layout(user_id: str, symbol: str, tab: str, timeframe: str, indicators: list[str], inspector_width: int) -> None:
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO layouts (id, user_id, symbol, tab, timeframe, indicators, inspector_width, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, symbol) DO UPDATE SET tab = ?, timeframe = ?, indicators = ?, inspector_width = ?, updated_at = ?""",
            (f"{user_id}_{symbol}", user_id, symbol, tab, timeframe, json.dumps(indicators), inspector_width, now, now, tab, timeframe, json.dumps(indicators), inspector_width, now),
        )
        conn.commit()


def get_layout(user_id: str, symbol: str) -> dict | None:
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM layouts WHERE user_id = ? AND symbol = ?", (user_id, symbol)).fetchone()
    if not row:
        return None
    item = dict(row)
    item['indicators'] = json.loads(item['indicators']) if item.get('indicators') else []
    return item


def list_layouts(user_id: str) -> list[dict]:
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM layouts WHERE user_id = ?", (user_id,)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item['indicators'] = json.loads(item['indicators']) if item.get('indicators') else []
        out.append(item)
    return out


def delete_layout(user_id: str, symbol: str) -> None:
    init_db()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM layouts WHERE user_id = ? AND symbol = ?", (user_id, symbol))
        conn.commit()


def get_preferences(user_id: str) -> dict:
    init_db()
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {"theme": "dark", "default_timezone": "UTC", "watchlists": [], "saved_layouts": {}}
    item = dict(row)
    item['watchlists'] = json.loads(item['watchlists']) if item.get('watchlists') else []
    item['saved_layouts'] = json.loads(item['saved_layouts']) if item.get('saved_layouts') else {}
    return item


def upsert_preferences(user_id: str, *, theme: str | None = None, default_timezone: str | None = None, watchlists: list | None = None, saved_layouts: dict | None = None) -> None:
    init_db()
    now = __import__('datetime').datetime.utcnow().isoformat()
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO preferences (user_id, theme, default_timezone, watchlists, saved_layouts)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET theme = ?, default_timezone = ?, watchlists = ?, saved_layouts = ?""",
            (user_id, theme or "dark", default_timezone or "UTC", json.dumps(watchlists or []), json.dumps(saved_layouts or {}),
             theme or "dark", default_timezone or "UTC", json.dumps(watchlists or []), json.dumps(saved_layouts or {})),
        )
        conn.commit()


# --- Event Snapshots for Backtest Reproducibility (Phase 2) ---