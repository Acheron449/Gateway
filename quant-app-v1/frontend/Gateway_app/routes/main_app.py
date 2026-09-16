from __future__ import annotations

import json

from flask import Blueprint, jsonify, render_template, request, session

from ..common import get_user_meta

main_bp = Blueprint('main_app', __name__)


@main_bp.route('/main')
def main_app():
    user_id = session.get('user_id')
    if not user_id:
        return render_template('index.html')
    meta = get_user_meta(user_id)
    return render_template('main.html', user_name=session.get('user_name', 'Trader'), credits=meta.get('credits', 1000), usage_remaining=meta.get('usage_remaining', 1000))


@main_bp.route('/api/market/history')
def api_market_history():
    data = {
        'symbol': request.args.get('symbol', 'EURUSD'),
        'timeframe': request.args.get('timeframe', '1h'),
        'candles': [
            {'time': '2026-09-12T00:00:00Z', 'open': 1.0832, 'high': 1.0846, 'low': 1.0829, 'close': 1.0841, 'volume': 1200},
            {'time': '2026-09-12T01:00:00Z', 'open': 1.0841, 'high': 1.0851, 'low': 1.0825, 'close': 1.0833, 'volume': 1380},
            {'time': '2026-09-12T02:00:00Z', 'open': 1.0833, 'high': 1.0857, 'low': 1.0828, 'close': 1.0853, 'volume': 1420},
            {'time': '2026-09-12T03:00:00Z', 'open': 1.0853, 'high': 1.0874, 'low': 1.0847, 'close': 1.0862, 'volume': 1600},
            {'time': '2026-09-12T04:00:00Z', 'open': 1.0862, 'high': 1.0869, 'low': 1.0840, 'close': 1.0848, 'volume': 1340},
        ],
    }
    return jsonify(data)
