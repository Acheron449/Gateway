from __future__ import annotations

import json

from flask import Blueprint, jsonify, render_template, request, session

from ..common import (
    get_user_by_email,
    get_user_meta,
    send_email_confirmation,
    set_user_meta,
    update_user_info,
    verify_password,
)


dashboard_bp = Blueprint('dashboard', __name__)


def _require_login():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return user_id


@dashboard_bp.route('/dashboard')
def dashboard():
    user_id = _require_login()
    if user_id is None:
        return render_template('index.html', user={}, tiers=[])
    user = get_user_by_email(session.get('user_email') or '') or {}
    meta = get_user_meta(user_id)
    return render_template('dashboard.html', user=user, meta=meta)


@dashboard_bp.route('/api/account')
def api_account():
    user_id = _require_login()
    if user_id is None:
        return jsonify({'logged_in': False}), 401
    user = get_user_by_email(session.get('user_email') or '') or {}
    meta = get_user_meta(user_id)
    account = {
        'logged_in': True,
        'user': {
            'id': user.get('id', user_id),
            'name': (user.get('name') or '').strip() or 'Trader',
            'last_name': (user.get('last_name') or '').strip(),
            'email': (user.get('email') or '').strip(),
        },
        'credits': meta.get('credits', 1000),
        'usage_remaining': meta.get('usage_remaining', 1000),
        'payment': meta.get('payment', {}),
        'api_inputs': meta.get('api_inputs', {}),
    }
    return jsonify(account)


@dashboard_bp.route('/api/account/update', methods=['POST'])
def api_account_update():
    user_id = _require_login()
    if user_id is None:
        return jsonify({'success': False, 'error': 'Authentication required.'}), 401
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    last_name = (payload.get('last_name') or '').strip()
    email = (payload.get('email') or '').strip().lower()
    data = {}
    if name:
        data['name'] = name
    if last_name:
        data['last_name'] = last_name
    if email:
        data['email'] = email

    if not data:
        return jsonify({'success': False, 'error': 'No fields provided.'}), 400
    ok = update_user_info(user_id, name=data.get('name'), last_name=data.get('last_name'), email=data.get('email'))
    if not ok:
        return jsonify({'success': False, 'error': 'Email may already be in use.'}), 409
    user = get_user_by_email(session.get('user_email') or '') or {}
    if email:
        session['user_email'] = email
        if user.get('email'):
            token = f"confirm-{user_id}-{email}"
            send_email_confirmation(email, token)
    if name:
        session['user_name'] = name
    return jsonify({'success': True, 'message': 'Account updated successfully.'})


@dashboard_bp.route('/api/account/payment', methods=['POST'])
def api_account_payment():
    user_id = _require_login()
    if user_id is None:
        return jsonify({'success': False, 'error': 'Authentication required.'}), 401
    payload = request.get_json(silent=True) or {}
    meta = get_user_meta(user_id)
    payment = meta.get('payment', {}) or {}
    payment.update({
        'provider': payload.get('provider', payment.get('provider', 'card')),
        'card_last4': payload.get('card_last4', payment.get('card_last4')),
        'billing_email': payload.get('billing_email', payment.get('billing_email')),
        'holder_name': payload.get('holder_name', payment.get('holder_name')),
    })
    meta['payment'] = payment
    set_user_meta(user_id, meta)
    return jsonify({'success': True, 'payment': payment})


@dashboard_bp.route('/api/account/api-inputs', methods=['POST'])
def api_account_api_inputs():
    user_id = _require_login()
    if user_id is None:
        return jsonify({'success': False, 'error': 'Authentication required.'}), 401
    payload = request.get_json(silent=True) or {}
    meta = get_user_meta(user_id)
    api_inputs = meta.get('api_inputs', {}) or {}
    api_inputs.update({
        'alpaca_key': payload.get('alpaca_key', api_inputs.get('alpaca_key')),
        'alpaca_secret': payload.get('alpaca_secret', api_inputs.get('alpaca_secret')),
        'finnhub_key': payload.get('finnhub_key', api_inputs.get('finnhub_key')),
        'openai_key': payload.get('openai_key', api_inputs.get('openai_key')),
    })
    meta['api_inputs'] = api_inputs
    set_user_meta(user_id, meta)
    return jsonify({'success': True, 'api_inputs': api_inputs})


@dashboard_bp.route('/api/account/topup', methods=['POST'])
def api_account_topup():
    user_id = _require_login()
    if user_id is None:
        return jsonify({'success': False, 'error': 'Authentication required.'}), 401
    payload = request.get_json(silent=True) or {}
    try:
        amount = int(payload.get('amount', 0) or 0)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Invalid top-up amount.'}), 400
    if amount <= 0:
        return jsonify({'success': False, 'error': 'Top-up amount must be positive.'}), 400
    meta = get_user_meta(user_id)
    meta['credits'] = (meta.get('credits', 0) or 0) + amount
    meta['usage_remaining'] = (meta.get('usage_remaining', 0) or 0) + amount
    set_user_meta(user_id, meta)
    return jsonify({'success': True, 'credits': meta['credits'], 'usage_remaining': meta['usage_remaining']})


@dashboard_bp.route('/api/account/confirm-email', methods=['POST'])
def api_account_confirm_email():
    user_id = _require_login()
    if user_id is None:
        return jsonify({'success': False, 'error': 'Authentication required.'}), 401
    payload = request.get_json(silent=True) or {}
    token = (payload.get('token') or '').strip()
    email = (payload.get('email') or '').strip().lower()
    if not token or not email:
        return jsonify({'success': False, 'error': 'Email and token are required.'}), 400
    expected = f"confirm-{user_id}-{email}"
    if token != expected:
        return jsonify({'success': False, 'error': 'Invalid confirmation token.'}), 400
    return jsonify({'success': True, 'message': 'Email confirmed.'})
