from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import smtplib
import sqlite3
import time
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from html import unescape
from pathlib import Path
from typing import Any, Optional

import bcrypt
from flask import request

BASE_DIR = Path(__file__).resolve().parent
USERS_DB = BASE_DIR / "users.db"
_RATE_LIMITS: dict[str, list[float]] = {}


def get_db_conn():
    conn = sqlite3.connect(str(USERS_DB))
    conn.row_factory = sqlite3.Row
    return conn


def init_user_db() -> None:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE,
            password_hash TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if 'last_name' not in cols:
        try:
            cur.execute('ALTER TABLE users ADD COLUMN last_name TEXT')
        except Exception:
            pass

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_meta (
            user_id INTEGER PRIMARY KEY,
            meta_json TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    conn.close()


def _rate_limit_exceeded(endpoint: str, limit: int = 5, window_seconds: int = 60) -> bool:
    ip = request.remote_addr or 'unknown'
    key = f"{endpoint}:{ip}"
    now = time.time()
    attempts = _RATE_LIMITS.setdefault(key, [])
    attempts[:] = [ts for ts in attempts if now - ts < window_seconds]
    if len(attempts) >= limit:
        return True
    attempts.append(now)
    return False


def _legacy_hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return f"{salt}${h}"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def verify_password(stored: str, password: str) -> bool:
    if not stored:
        return False
    try:
        if stored.startswith('$2'):
            return bcrypt.checkpw(password.encode('utf-8'), stored.encode('utf-8'))
    except ValueError:
        pass
    try:
        salt, h = stored.split('$', 1)
    except Exception:
        return False
    calc = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return calc == h


def create_user(name: str | None, email: str, password: str, last_name: str | None = None) -> Optional[int]:
    if not email or not password:
        return None
    first_name = (name or '').strip()
    ln = (last_name or '').strip()
    if not ln and first_name:
        parts = first_name.split()
        if len(parts) > 1:
            ln = parts[-1]
            first_name = ' '.join(parts[:-1])
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO users (name, last_name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)',
            (first_name or None, ln or None, email, hash_password(password), datetime.utcnow().isoformat()),
        )
        conn.commit()
        user_id = cur.lastrowid
        meta = {'credits': 1000, 'usage_remaining': 1000, 'payment': {}, 'api_inputs': {}}
        cur.execute('INSERT OR REPLACE INTO user_meta (user_id, meta_json) VALUES (?, ?)', (user_id, __import__('json').dumps(meta)))
        conn.commit()
    except sqlite3.IntegrityError:
        user_id = None
    finally:
        conn.close()
    return user_id


def get_user_by_email(email: str) -> Optional[dict]:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT id, name, last_name, email, created_at FROM users WHERE email = ? LIMIT 1', (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d.setdefault('name', d.get('name') or '')
    d.setdefault('last_name', d.get('last_name') or '')
    return d


def update_user_info(user_id: int, name: str | None = None, last_name: str | None = None, email: str | None = None) -> bool:
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        if name is not None and last_name is not None and email is not None:
            cur.execute('UPDATE users SET name = ?, last_name = ?, email = ? WHERE id = ?', (name, last_name, email, user_id))
        elif name is not None and last_name is not None:
            cur.execute('UPDATE users SET name = ?, last_name = ? WHERE id = ?', (name, last_name, user_id))
        elif name is not None:
            cur.execute('UPDATE users SET name = ? WHERE id = ?', (name, user_id))
        elif last_name is not None:
            cur.execute('UPDATE users SET last_name = ? WHERE id = ?', (last_name, user_id))
        elif email is not None:
            cur.execute('UPDATE users SET email = ? WHERE id = ?', (email, user_id))
        else:
            return True
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_user_meta(user_id: int) -> dict:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT meta_json FROM user_meta WHERE user_id = ? LIMIT 1', (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row['meta_json']:
        return {'credits': 1000, 'usage_remaining': 1000, 'payment': {}, 'api_inputs': {}}
    try:
        import json
        payload = json.loads(row['meta_json']) or {}
        payload.setdefault('credits', 1000)
        payload.setdefault('usage_remaining', 1000)
        payload.setdefault('payment', {})
        payload.setdefault('api_inputs', {})
        return payload
    except Exception:
        return {'credits': 1000, 'usage_remaining': 1000, 'payment': {}, 'api_inputs': {}}


def set_user_meta(user_id: int, meta: dict) -> None:
    conn = get_db_conn()
    cur = conn.cursor()
    import json
    normalized = meta or {'credits': 1000, 'usage_remaining': 1000, 'payment': {}, 'api_inputs': {}}
    normalized.setdefault('credits', 1000)
    normalized.setdefault('usage_remaining', 1000)
    normalized.setdefault('payment', {})
    normalized.setdefault('api_inputs', {})
    cur.execute('INSERT OR REPLACE INTO user_meta (user_id, meta_json) VALUES (?, ?)', (user_id, json.dumps(normalized)))
    conn.commit()
    conn.close()


def send_email_message(to_email: str, subject: str, body: str) -> bool:
    smtp_host = os.getenv('QUANT_SMTP_HOST')
    if not smtp_host:
        print(f"[demo-email] To={to_email} | Subject={subject} | Body={body}")
        return True
    from_addr = os.getenv('QUANT_SMTP_FROM', 'no-reply@gateway.local')
    port = int(os.getenv('QUANT_SMTP_PORT', '587'))
    username = os.getenv('QUANT_SMTP_USERNAME')
    password = os.getenv('QUANT_SMTP_PASSWORD')
    msg = EmailMessage()
    msg['From'] = from_addr
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(smtp_host, port) as server:
            if username and password:
                server.starttls()
                server.login(username, password)
            server.send_message(msg)
        return True
    except Exception as exc:
        print(f"SMTP send failed for {to_email}: {exc}")
        return False


def send_email_confirmation(to_email: str, token: str) -> bool:
    subject = 'Gateway Account Email Confirmation'
    body = (
        'Use this confirmation token in your dashboard to confirm the email change:\n\n'
        f'{token}\n\n'
        'If you did not request this change, you can safely ignore this email.'
    )
    return send_email_message(to_email, subject, body)


def authenticate_user(email: str, password: str) -> bool:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT password_hash FROM users WHERE email = ? LIMIT 1', (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    return verify_password(row['password_hash'], password)


def fetch_forex_factory_news(limit: int = 5):
    candidate_urls = [
        'https://www.forexfactory.com/calendar.php?day=today',
        'https://www.forexfactory.com/',
        'https://www.forexfactory.com/thread/1247273-free-news-api-machine-learning-live-trading-and',
    ]
    now_iso = datetime.utcnow().isoformat() + 'Z'

    for url in candidate_urls:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
            if not html or 'Just a moment' in html or 'cloudflare' in html.lower():
                continue
            title_match = re.search(r'<title>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
            title = unescape((title_match.group(1) if title_match else 'Forex Factory').strip())
            snippets = re.findall(r'>([^<>]{30,220})<', html)
            clean = []
            seen = set()
            for snippet in snippets:
                text = re.sub(r'\s+', ' ', unescape(snippet)).strip()
                if len(text) < 40 or len(text) > 220:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                clean.append(text)
            if clean:
                items = []
                for idx, text in enumerate(clean[:limit], start=1):
                    title_prefix = title if idx == 1 else 'Forex Factory update'
                    items.append({
                        'title': f'{title_prefix} ({idx})',
                        'headline': text,
                        'summary': text,
                        'source': 'Forex Factory',
                        'url': url,
                        'published_at': now_iso,
                    })
                return items[:limit]
        except Exception:
            continue

    fallback = [
        {
            'title': 'Forex Factory News API thread',
            'headline': 'Free News API (Machine Learning, Live Trading, and Backtesting)',
            'summary': 'The referenced Forex Factory thread discusses using event data, macro calendars, and machine-learning pipelines for trading and backtesting.',
            'source': 'Forex Factory',
            'url': 'https://www.forexfactory.com/thread/1247273-free-news-api-machine-learning-live-trading-and',
            'published_at': now_iso,
        },
        {
            'title': 'Economic calendar signal data',
            'headline': 'Forex Factory provides access to central-bank and macro event timing for news-driven trade planning.',
            'summary': 'The calendar helps traders align execution around events and macro catalysts while still preserving a backtested risk framework.',
            'source': 'Forex Factory',
            'url': 'https://www.forexfactory.com/calendar.php',
            'published_at': now_iso,
        },
        {
            'title': 'Event-driven strategy research',
            'headline': 'Machine learning and live trading workflows often combine economic event feeds with model-based filtering and signal scoring.',
            'summary': 'This approach supports research automation, historical replay, and event-aware signal generation for multi-asset strategies.',
            'source': 'Forex Factory',
            'url': 'https://www.forexfactory.com/thread/1247273-free-news-api-machine-learning-live-trading-and',
            'published_at': now_iso,
        },
    ]
    return fallback[:limit]
