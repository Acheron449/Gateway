from __future__ import annotations

import hashlib
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
    """Best-effort Forex Factory news retrieval with graceful fallback."""
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


@app.route('/api/news/forex-factory', methods=['GET'])
def api_forex_factory_news():
    try:
        limit = int(request.args.get('limit', 5))
    except ValueError:
        limit = 5
    limit = max(1, min(limit, 10))
    return jsonify(fetch_forex_factory_news(limit=limit)), 200


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


@app.route('/main')
def main_app():
    """Authenticated main application page — TradingView-like layout with strategy creator."""
    u = session.get('user')
    if not u:
        return render_template('index.html', tiers=[{"name": "Free", "price": "$0", "credits": "800 credits", "featured": False, "cta": "Get Started Free"}])
    return render_template('main.html', user=u)


@app.route('/api/market/history')
def api_market_history():
    """Return synthetic OHLC history for prototype charting.

    Query params:
    - symbol (default: EURUSD)
    - tf (timeframe key: 1m,5m,15m,1h,4h,1d)
    - limit (number of candles, default 500)
    """
    symbol = request.args.get('symbol', 'EURUSD').upper()
    tf = request.args.get('tf', '1m')
    try:
        limit = int(request.args.get('limit', 500))
    except Exception:
        limit = 500
    limit = max(10, min(limit, 2000))

    # mapping timeframe to seconds
    tf_map = {'1m': 60, '5m': 60 * 5, '15m': 60 * 15, '1h': 60 * 60, '4h': 60 * 60 * 4, '1d': 60 * 60 * 24}
    step = tf_map.get(tf, 60)

    # try backend history endpoint if available
    backend_url = f"/history/{symbol}"
    try:
        # prefer backend fastapi history if available
        from urllib import request as urlreq, parse
        host = request.host_url.rstrip('/')
        url = f"{host}/history/{symbol}"
        # call backend (same host) — if it returns 200 we'll try to use it (but backend may require Alpaca)
        with urlreq.urlopen(url, timeout=3) as resp:
            import json
            body = resp.read()
            data = json.loads(body.decode('utf-8'))
            if isinstance(data, list) and data:
                # resample/convert to requested tf by simple aggregation if needed (baseline assumes 1h historical)
                # convert incoming candles which are in 'time' (unix sec) to our timeframe by grouping
                # naive aggregation: round down to nearest step
                out = {}
                for c in data:
                    t = int(c.get('time', 0))
                    bucket = (t // step) * step
                    entry = out.get(bucket)
                    if not entry:
                        out[bucket] = {'time': bucket, 'open': c['open'], 'high': c['high'], 'low': c['low'], 'close': c['close']}
                    else:
                        entry['high'] = max(entry['high'], c['high'])
                        entry['low'] = min(entry['low'], c['low'])
                        entry['close'] = c['close']
                items = list(out.values())
                items.sort(key=lambda x: x['time'])
                # trim to limit (last N)
                items = items[-limit:]
                return jsonify(items), 200
    except Exception:
        pass

    # fallback: synthetic random-walk generator
    import random, time
    now = int(time.time())
    # align last timestamp to timeframe boundary
    last_ts = (now // step) * step
    # start price (seed by symbol hash)
    seed = abs(hash(symbol)) % 10000
    base = 1.0 + (seed % 1000) / 1000.0 * 1.2
    # generate moving series
    candles = []
    prev_close = base
    for i in range(limit, 0, -1):
        t = last_ts - (i - 1) * step
        # simulate volatility depending on timeframe
        vol = 0.0003 if tf == '1m' else 0.0008 if tf == '5m' else 0.002 if tf == '15m' else 0.006 if tf == '1h' else 0.02
        open_p = prev_close * (1 + random.uniform(-vol, vol))
        high_p = open_p * (1 + random.uniform(0, vol * 1.8))
        low_p = open_p * (1 - random.uniform(0, vol * 1.8))
        close_p = low_p + random.random() * (high_p - low_p)
        prev_close = close_p
        candles.append({'time': int(t), 'open': round(open_p, 5), 'high': round(high_p, 5), 'low': round(low_p, 5), 'close': round(close_p, 5)})
    return jsonify(candles), 200


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
    if name is not None or last_name is not None:
        ok = update_user_info(user['id'], name=name if name is not None else user.get('name'), last_name=last_name if last_name is not None else user.get('last_name'))
        if not ok:
            return jsonify({'message': 'Failed to update name'}), 500
        # refresh session user
        updated_user = get_user_by_email(user['email'])
        session['user'] = {'id': updated_user['id'], 'email': updated_user['email'], 'name': updated_user.get('name'), 'last_name': updated_user.get('last_name')}

    # handle email change: require confirmation
    if email and email != user.get('email'):
        token = secrets.token_hex(16)
        meta = get_user_meta(user['id'])
        meta['pending_email'] = email
        meta['email_confirm_token'] = token
        set_user_meta(user['id'], meta)
        email_sent = send_email_confirmation(email, token)
        payload = {'message': 'Email change requires confirmation', 'confirmation_token': token}
        if email_sent:
            payload['email_sent'] = True
        else:
            payload['email_sent'] = False
        return jsonify(payload), 202

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
    first_name = (data.get('first_name') or data.get('name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    if not first_name:
        # accept a user-provided full name string as a fallback
        full_name = (data.get('full_name') or '').strip()
        if full_name:
            parts = full_name.split()
            first_name = parts[0] if parts else ''
            if len(parts) > 1:
                last_name = ' '.join(parts[1:])
    if not first_name and ' ' in (data.get('name') or ''):
        parts = (data.get('name') or '').split()
        first_name = parts[0]
        last_name = ' '.join(parts[1:])
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not email or not password or not first_name:
        return jsonify({'message': 'First name, email and password required'}), 400
    user_id = create_user(first_name, email, password, last_name=last_name)
    if user_id is None:
        return jsonify({'message': 'User already exists'}), 409
    user = {'id': user_id, 'email': email, 'name': first_name, 'last_name': last_name}
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
