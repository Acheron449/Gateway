from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[3] / "quant_app.db"


@contextmanager
def get_connection():
    connection = sqlite3.connect(DB_PATH)
    try:
        yield connection
    finally:
        connection.close()