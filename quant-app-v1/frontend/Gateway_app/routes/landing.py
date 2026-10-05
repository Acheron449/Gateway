from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request, session

from ..common import (
    _rate_limit_exceeded,
    authenticate_user,
    create_user,
    get_user_by_email,
    get_user_meta,
    hash_password,
    init_user_db,
    send_email_confirmation,
    set_user_meta,
    update_user_info,
    verify_password,
)

landing_bp = Blueprint('landing', __name__)


@landing_bp.route('/')
def index():
    user = {'name': session.get('user_name', ''), 'email': session.get('user_email', '')}
    tiers = [
        {'name': 'Starter', 'price': '$29', 'credits': '2,000 Credits', 'cta': 'Get Started', 'featured': False},
        {'name': 'Pro', 'price': '$79', 'credits': '7,000 Credits', 'cta': 'Start Pro', 'featured': True},
        {'name': 'Scale', 'price': '$149', 'credits': '16,000 Credits', 'cta': 'Scale Up', 'featured': False},
    ]
    return render_template('index.html', user=user, tiers=tiers)


@landing_bp.route('/api/auth/signup', methods=['POST'])
def api_signup():
    if _rate_limit_exceeded('signup', limit=10, window_seconds=60):
        return jsonify({'success': False, 'error': 'Too many signup attempts. Please wait a moment.'}), 429
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    last_name = (payload.get('last_name') or '').strip()
    email = (payload.get('email') or '').strip().lower()
    password = payload.get('password') or ''
    if not email or not password:
        return jsonify({'success': False, 'error': 'Email and password are required.'}), 400
    user_id = create_user(name, email, password, last_name=last_name)
    if user_id is None:
        return jsonify({'success': False, 'error': 'Email already exists or account could not be created.'}), 409
    session['user_id'] = user_id
    session['user_email'] = email
    session['user_name'] = name or (get_user_by_email(email) or {}).get('name') or ''
    return jsonify({'success': True, 'message': 'Account created successfully.'})


@landing_bp.route('/api/auth/login', methods=['POST'])
def api_login():
    if _rate_limit_exceeded('login', limit=10, window_seconds=60):
        return jsonify({'success': False, 'error': 'Too many login attempts. Please wait a moment.'}), 429
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip().lower()
    password = payload.get('password') or ''
    if not email or not password:
        return jsonify({'success': False, 'error': 'Email and password are required.'}), 400
    user = get_user_by_email(email)
    if not user or not authenticate_user(email, password):
        return jsonify({'success': False, 'error': 'Invalid email or password.'}), 401
    session['user_id'] = user['id']
    session['user_email'] = user['email']
    session['user_name'] = (user.get('name') or '').strip() or 'Trader'
    return jsonify({'success': True, 'redirect': '/main', 'message': 'Login successful.'})


@landing_bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({'success': True})


@landing_bp.route('/api/auth/me')
def api_me():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'logged_in': False})
    user = get_user_by_email(session.get('user_email') or '') or {}
    if not user and user_id:
        user = {'id': user_id, 'name': session.get('user_name', 'Trader'), 'last_name': '', 'email': session.get('user_email', '')}
    meta = get_user_meta(user_id)
    payload = {
        'logged_in': True,
        'user': {
            'id': user.get('id', user_id),
            'name': (user.get('name') or '').strip() or 'Trader',
            'last_name': (user.get('last_name') or '').strip(),
            'email': (user.get('email') or '').strip(),
        },
        'credits': meta.get('credits', 1000),
        'usage_remaining': meta.get('usage_remaining', 1000),
    }
    return jsonify(payload)


@landing_bp.route('/api/news/forex-factory')
def api_news_forex_factory():
    return jsonify(
        {
            "items": [],
            "status": "unavailable",
            "message": "This legacy news source is unavailable; use the provenance-backed news endpoint",
            "provenance": {
                "source": "forex-factory",
                "provider_version": "legacy-disabled",
                "coverage": "unavailable",
                "entitlement": "unavailable",
            },
        }
    ), 503


@landing_bp.route('/api/generate', methods=['POST'])
def api_generate():
    payload = request.get_json(silent=True) or {}
    strategy = payload.get('strategy') or payload.get('prompt') or 'Breakout trend system'
    details = {
        'strategy': strategy,
        'status': 'draft',
        'summary': 'Generator is active; hook this endpoint up to your strategy engine for live creation.',
    }
    return jsonify({'success': True, 'data': details})
