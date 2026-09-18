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
    """Create necessary tables for simulated orders and backtest runs if they don't exist."""
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
    assignments = []
    values = []
    for key, value in payload.items():
        if value is None:
            continue
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