from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import bcrypt
from flask import Flask, jsonify, render_template, request, session

BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "static" / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

# Secret key for session cookies — prefer to set QUANT_FRONTEND_SECRET in environment for production
app.secret_key = os.getenv('QUANT_FRONTEND_SECRET') or os.urandom(24).hex()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_PERMANENT'] = True
app.config.setdefault('SESSION_COOKIE_NAME', 'gateway_session')

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
    # Ensure last_name column exists (SQLite ALTER if missing)
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if 'last_name' not in cols:
        try:
            cur.execute('ALTER TABLE users ADD COLUMN last_name TEXT')
        except Exception:
            # older SQLite versions may error; ignore (best-effort migration)
            pass

    # user_meta table stores JSON metadata: credits, payment_info, api_inputs, etc.
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
    # Backwards compatibility for previously stored SHA-256 salted hashes
    try:
        salt, h = stored.split('$', 1)
    except Exception:
        return False
    calc = hashlib.sha256((salt + password).encode('utf-8')).hexdigest()
    return calc == h


def create_user(name: str | None, email: str, password: str, last_name: str | None = None) -> Optional[int]:
    """Create a user. Accepts name (first/full) and optional last_name.
    Splits name if last_name not provided by taking the last token as last_name.
    """
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
        cur.execute('INSERT INTO users (name, last_name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)',
                    (first_name or None, ln or None, email, hash_password(password), datetime.utcnow().isoformat()))
        conn.commit()
        user_id = cur.lastrowid
        # initialize empty metadata for the user
        cur.execute('INSERT OR REPLACE INTO user_meta (user_id, meta_json) VALUES (?, ?)', (user_id, '{}'))
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
    # Normalize fields
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
        return {}
    try:
        import json
        return json.loads(row['meta_json'])
    except Exception:
        return {}


def set_user_meta(user_id: int, meta: dict) -> None:
    conn = get_db_conn()
    cur = conn.cursor()
    import json
    cur.execute('INSERT OR REPLACE INTO user_meta (user_id, meta_json) VALUES (?, ?)', (user_id, json.dumps(meta)))
    conn.commit()
    conn.close()


def authenticate_user(email: str, password: str) -> bool:
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute('SELECT password_hash FROM users WHERE email = ? LIMIT 1', (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    return verify_password(row['password_hash'], password)


init_user_db()


@app.route("/")
def home():

    pricing_tiers = [
        {"name": "Free", "price": "$0", "credits": "800 credits", "featured": False, "cta": "Get Started Free"},
        {"name": "Starter", "price": "$9", "credits": "2,000 credits/mo", "featured": False, "cta": "Select Plan"},
        {"name": "Pro", "price": "$29", "credits": "4,000 credits/mo", "featured": True, "cta": "Start Pro Trial"},
        {"name": "Elite", "price": "$79", "credits": "8,000 credits/mo", "featured": False, "cta": "Select Plan"}
    ]
    return render_template("index.html", tiers=pricing_tiers)


@app.route("/api/generate", methods=["POST"])
def generate_logic():
    data = request.get_json() or {}
    prompt_text = data.get("prompt", "")
    return jsonify({
        "status": "completed",
        "metrics": {
            "win_rate": "68.4%",
            "drawdown": "-3.8%",
            "trades": "126",
            "profit_factor": "2.34"
        }
    })


@app.route('/dashboard')
def dashboard():
    # require authentication
    u = session.get('user')
    if not u:
        # not logged in, show landing and open auth modal
        return render_template('index.html', tiers=[
            {"name": "Free", "price": "$0", "credits": "800 credits", "featured": False, "cta": "Get Started Free"},
        ])
    # render dashboard template; client JS will fetch full account info
    return render_template('dashboard.html', user=u)


@app.route('/api/account', methods=['GET', 'POST'])
def api_account():
    u = session.get('user')
    if not u:
        return jsonify({'message': 'Unauthorized'}), 401
    user = get_user_by_email(u.get('email'))
    if not user:
        return jsonify({'message': 'User not found'}), 404
    if request.method == 'GET':
        meta = get_user_meta(user['id'])
        # provide defaults
        response = {
            'id': user['id'],
            'name': user.get('name'),
            'last_name': user.get('last_name'),
            'email': user.get('email'),
            'created_at': user.get('created_at'),
            'meta': {
                'credits': meta.get('credits', 1000),
                'usage_remaining': meta.get('usage_remaining', 1000),
                'payment': meta.get('payment', {}),
                'api_inputs': meta.get('api_inputs', {})
            }
        }
        return jsonify(response), 200
    # POST - update profile/meta
    data = request.get_json() or {}
    name = data.get('name')
    last_name = data.get('last_name')
    email = data.get('email')
    payment = data.get('payment')
    api_inputs = data.get('api_inputs')
    # update DB user info (name/last_name) immediately
    if name or last_name:
        ok = update_user_info(user['id'], name=name, last_name=last_name)
        if not ok:
            return jsonify({'message': 'Failed to update name'}), 500
        # refresh session user
        updated_user = get_user_by_email(user['email'])
        session['user'] = {'id': updated_user['id'], 'email': updated_user['email'], 'name': updated_user.get('name'), 'last_name': updated_user.get('last_name')}

    # handle email change: require confirmation
    if email and email != user.get('email'):
        # generate confirmation token and store pending_email in meta
        import secrets
        token = secrets.token_hex(16)
        meta = get_user_meta(user['id'])
        meta['pending_email'] = email
        meta['email_confirm_token'] = token
        set_user_meta(user['id'], meta)
        # In a real app, send email to `email` with the token / confirmation link. For demo, return token in response.
        return jsonify({'message': 'Email change requires confirmation', 'confirmation_token': token}), 202

    # update meta
    meta = get_user_meta(user['id'])
    if payment is not None:
        meta['payment'] = payment
    if api_inputs is not None:
        meta['api_inputs'] = api_inputs
    # if credits/usage provided allow explicit set
    if 'credits' in data:
        meta['credits'] = data.get('credits')
    if 'usage_remaining' in data:
        meta['usage_remaining'] = data.get('usage_remaining')
    set_user_meta(user['id'], meta)
    return jsonify({'message': 'Account updated', 'meta': meta}), 200


@app.route('/api/billing/topup', methods=['POST'])
def api_billing_topup():
    u = session.get('user')
    if not u:
        return jsonify({'message': 'Unauthorized'}), 401
    user = get_user_by_email(u.get('email'))
    if not user:
        return jsonify({'message': 'User not found'}), 404
    data = request.get_json() or {}
    amount = data.get('amount')
    if amount is None:
        return jsonify({'message': 'Amount required'}), 400
    try:
        amount_val = float(amount)
    except (ValueError, TypeError):
        return jsonify({'message': 'Invalid amount'}), 400
    if amount_val <= 0:
        return jsonify({'message': 'Amount must be positive'}), 400
    # Dummy payment processing simulation
    # In production: integrate with payment gateway and tokenise details
    import time
    time.sleep(0.2)  # simulate small delay
    meta = get_user_meta(user['id'])
    credits = meta.get('credits', 1000)
    # simple conversion: $1 -> 100 credits
    add_credits = int(amount_val * 100)
    credits += add_credits
    meta['credits'] = credits
    # increase usage_remaining similarly
    meta['usage_remaining'] = meta.get('usage_remaining', 1000) + add_credits
    set_user_meta(user['id'], meta)
    return jsonify({'message': 'Top-up successful', 'added_credits': add_credits, 'credits': credits}), 200


@app.route('/api/account/confirm_email', methods=['POST'])
def api_account_confirm_email():
    u = session.get('user')
    if not u:
        return jsonify({'message': 'Unauthorized'}), 401
    user = get_user_by_email(u.get('email'))
    if not user:
        return jsonify({'message': 'User not found'}), 404
    data = request.get_json() or {}
    token = data.get('token')
    if not token:
        return jsonify({'message': 'Token required'}), 400
    meta = get_user_meta(user['id'])
    if not meta.get('email_confirm_token') or meta.get('email_confirm_token') != token:
        return jsonify({'message': 'Invalid token'}), 400
    pending = meta.get('pending_email')
    if not pending:
        return jsonify({'message': 'No pending email change'}), 400
    # apply email change
    ok = update_user_info(user['id'], email=pending)
    if not ok:
        return jsonify({'message': 'Email already in use'}), 409
    # clear pending
    meta.pop('pending_email', None)
    meta.pop('email_confirm_token', None)
    set_user_meta(user['id'], meta)
    # refresh session user
    updated_user = get_user_by_email(pending)
    session['user'] = {'id': updated_user['id'], 'email': updated_user['email'], 'name': updated_user.get('name'), 'last_name': updated_user.get('last_name')}
    return jsonify({'message': 'Email change confirmed', 'email': pending}), 200


@app.route('/api/auth/signup', methods=['POST'])
def api_signup():
    if _rate_limit_exceeded('signup'):
        return jsonify({'message': 'Too many signup attempts. Please wait a minute and try again.'}), 429
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not email or not password:
        return jsonify({'message': 'Email and password required'}), 400
    user_id = create_user(name, email, password)
    if user_id is None:
        return jsonify({'message': 'User already exists'}), 409
    user = {'id': user_id, 'email': email, 'name': name}
    session.clear()
    session['user'] = user
    return jsonify({'message': 'User created', 'user_id': user_id, 'user': user}), 201


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    if _rate_limit_exceeded('login'):
        return jsonify({'message': 'Too many login attempts. Please wait a minute and try again.'}), 429
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not email or not password:
        return jsonify({'message': 'Email and password required'}), 400
    ok = authenticate_user(email, password)
    if not ok:
        return jsonify({'message': 'Invalid credentials'}), 401
    user = get_user_by_email(email)
    session.clear()
    session['user'] = {'id': user['id'], 'email': user['email'], 'name': user.get('name')}
    return jsonify({'message': 'Authenticated', 'user': session['user']}), 200


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'message': 'Logged out'}), 200


@app.route('/api/auth/me', methods=['GET'])
def api_me():
    u = session.get('user')
    if not u:
        return jsonify({'authenticated': False}), 200
    return jsonify({'authenticated': True, 'user': u}), 200


if __name__ == "__main__":
    init_user_db()
    app.run(debug=True, port=5000)
