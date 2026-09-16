from __future__ import annotations

import os
import sys
from pathlib import Path

from flask import Flask

if __package__ in {None, ''}:
    parent_dir = str(Path(__file__).resolve().parents[1])
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
    __package__ = 'Gateway_app'

from .common import init_user_db
from .routes import register_blueprints

BASE_DIR = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "static" / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

from flask import session

app.secret_key = os.getenv('QUANT_FRONTEND_SECRET') or os.urandom(24).hex()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_PERMANENT'] = True
app.config.setdefault('SESSION_COOKIE_NAME', 'gateway_session')

# Register blueprints and initialize the user DB
register_blueprints(app)
init_user_db()


# Provide a consistent user context to all templates so Jinja won't complain
@app.context_processor
def inject_user_context():
    try:
        # import inside to avoid circular import at module import time
        from .common import get_user_by_email, get_user_meta
    except Exception:
        # fallback for script-run mode
        from common import get_user_by_email, get_user_meta

    user = {}
    meta = {}
    email = session.get('user_email')
    user_id = session.get('user_id')
    if email:
        user = get_user_by_email(email) or {'name': session.get('user_name', ''), 'email': email}
    elif user_id:
        meta = get_user_meta(user_id) or {}
        user = {'name': session.get('user_name', ''), 'email': session.get('user_email', '')}
    else:
        user = {}

    if user_id and not meta:
        try:
            meta = get_user_meta(user_id) or {}
        except Exception:
            meta = {}

    tiers = [
        {'name': 'Starter', 'price': '$29', 'credits': '2,000 Credits', 'cta': 'Get Started', 'featured': False},
        {'name': 'Pro', 'price': '$79', 'credits': '7,000 Credits', 'cta': 'Start Pro', 'featured': True},
        {'name': 'Scale', 'price': '$149', 'credits': '16,000 Credits', 'cta': 'Scale Up', 'featured': False},
    ]

    return {
        'user': user,
        'tiers': tiers,
        'user_meta': meta,
    }


if __name__ == "__main__":
    app.run(debug=True, port=5000)
