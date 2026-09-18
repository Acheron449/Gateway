from __future__ import annotations

import json

from flask import Blueprint, jsonify, render_template, request, session

from ..common import get_user_meta

main_bp = Blueprint('main_app', __name__)


@main_bp.route('/main')
def main_app():
    user_id = session.get('user_id')
    if not user_id:
        return render_template('index.html', user={}, tiers=[])
    user = {'name': session.get('user_name', 'Trader'), 'email': session.get('user_email', '')}
    meta = get_user_meta(user_id)
    return render_template('main.html', user=user, user_name=user['name'], credits=meta.get('credits', 1000), usage_remaining=meta.get('usage_remaining', 1000))


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


@main_bp.route('/api/backtest', methods=['POST'])
def api_backtest():
    """Lightweight front-end backtest runner (prototype).
    Accepts JSON payload with either `bars` (list of candles) or `symbol`/`timeframe` to use the built-in history.
    Returns a simple SMA crossover analysis and basic metrics so the front-end can display results.
    """
    payload = request.get_json(silent=True) or {}
    bars = payload.get('bars')
    # if no bars provided, use the internal market history route sample
    if not bars:
        hist_resp = api_market_history()
        hist = json.loads(hist_resp.get_data(as_text=True))
        bars = hist.get('candles', [])

    # normalize closes
    closes = [float(b.get('close', 0)) for b in bars if b and 'close' in b]
    times = [b.get('time') for b in bars]

    # adaptive SMA crossover strategy: choose windows based on available data
    if len(closes) < 2:
        return jsonify({'error': 'Not enough data for backtest', 'analysis': {}}), 400
    long = min(6, len(closes))
    short = max(2, long // 2)

    def sma(data, window):
        res = []
        for i in range(len(data)):
            if i + 1 < window:
                res.append(None)
            else:
                res.append(sum(data[i + 1 - window:i + 1]) / window)
        return res

    sma_short = sma(closes, short)
    sma_long = sma(closes, long)

    position = None
    entry_price = None
    trades = []

    for i in range(len(closes)):
        if sma_short[i] is None or sma_long[i] is None:
            continue
        # crossover up -> buy
        if sma_short[i] > sma_long[i] and position is None:
            position = 'long'
            entry_price = closes[i]
            trades.append({'entry_idx': i, 'entry_price': entry_price, 'entry_time': times[i], 'exit_idx': None, 'exit_price': None, 'exit_time': None, 'pnl_pct': None})
        # crossover down -> close
        if sma_short[i] < sma_long[i] and position == 'long':
            exit_price = closes[i]
            trade = trades[-1]
            trade['exit_idx'] = i
            trade['exit_price'] = exit_price
            trade['exit_time'] = times[i]
            trade['pnl_pct'] = ((exit_price - trade['entry_price']) / trade['entry_price']) * 100.0
            position = None
            entry_price = None

    # if position still open, close at last
    if position == 'long' and trades:
        last = trades[-1]
        last_price = closes[-1]
        last['exit_idx'] = len(closes) - 1
        last['exit_price'] = last_price
        last['exit_time'] = times[-1]
        last['pnl_pct'] = ((last_price - last['entry_price']) / last['entry_price']) * 100.0

    wins = [t for t in trades if t.get('pnl_pct') is not None and t['pnl_pct'] > 0]
    losses = [t for t in trades if t.get('pnl_pct') is not None and t['pnl_pct'] <= 0]
    win_rate = (len(wins) / (len(wins) + len(losses))) * 100.0 if (wins or losses) else 0.0
    total_pnl = sum((t.get('pnl_pct') or 0.0) for t in trades)
    avg_pnl = (total_pnl / len(trades)) if trades else 0.0
    max_drawdown = min((t.get('pnl_pct') or 0.0) for t in trades) if trades else 0.0

    analysis = {
        'trades_count': len(trades),
        'win_rate': round(win_rate, 2),
        'avg_pnl_pct': round(avg_pnl, 3),
        'total_pnl_pct': round(total_pnl, 3),
        'max_drawdown_pct': round(max_drawdown, 3),
        'trades': trades,
    }
    return jsonify({'success': True, 'analysis': analysis})
