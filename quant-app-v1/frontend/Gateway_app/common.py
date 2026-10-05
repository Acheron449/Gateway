from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import smtplib
import sqlite3
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional

import bcrypt
from cryptography.fernet import Fernet
from flask import request

BASE_DIR = Path(__file__).resolve().parent
USERS_DB = BASE_DIR / "users.db"
_RATE_LIMITS: dict[str, list[float]] = {}

# Encryption for API keys at rest
_FERNET_KEY_ENV = "QUANT_API_ENCRYPTION_KEY"


def _get_fernet() -> Fernet | None:
    """Get Fernet instance from environment key."""
    key_b64 = os.getenv(_FERNET_KEY_ENV)
    if not key_b64:
        return None
    try:
        key = base64.urlsafe_b64decode(key_b64)
        return Fernet(key)
    except Exception:
        return None


def encrypt_api_key(plain: str) -> str | None:
    """Encrypt an API key for storage. Returns None if encryption not configured."""
    f = _get_fernet()
    if not f:
        return None
    return f.encrypt(plain.encode()).decode()


def decrypt_api_key(cipher: str) -> str | None:
    """Decrypt an API key from storage. Returns None if decryption fails."""
    f = _get_fernet()
    if not f:
        return None
    try:
        return f.decrypt(cipher.encode()).decode()
    except Exception:
        return None


def encrypt_dict_values(data: dict, keys_to_encrypt: set[str]) -> dict:
    """Encrypt specified keys in a dictionary."""
    result = data.copy()
    for key in keys_to_encrypt:
        if key in result and result[key]:
            encrypted = encrypt_api_key(result[key])
            if encrypted:
                result[key] = encrypted
    return result


def decrypt_dict_values(data: dict, keys_to_decrypt: set[str]) -> dict:
    """Decrypt specified keys in a dictionary."""
    result = data.copy()
    for key in keys_to_decrypt:
        if key in result and result[key]:
            decrypted = decrypt_api_key(result[key])
            if decrypted:
                result[key] = decrypted
    return result


API_KEY_FIELDS = {"alpaca_key", "alpaca_secret", "finnhub_key", "openai_key"}


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
        # Decrypt API keys for use
        api_inputs = payload.get('api_inputs', {})
        if api_inputs:
            payload['api_inputs'] = decrypt_dict_values(api_inputs, API_KEY_FIELDS)
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
    # Encrypt API keys before storage
    api_inputs = normalized.get('api_inputs', {})
    if api_inputs:
        normalized['api_inputs'] = encrypt_dict_values(api_inputs, API_KEY_FIELDS)
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
    """Return no records; Gateway does not scrape or synthesize news."""
    del limit
    return []
