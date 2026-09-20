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

# Security configuration
_env = os.getenv('GATEWAY_ENV', 'local').lower()
_is_production = _env in ('production', 'prod')

# Require secret key in production
secret_key = os.getenv('QUANT_FRONTEND_SECRET')
if _is_production and not secret_key:
    raise RuntimeError("QUANT_FRONTEND_SECRET must be set in production")
app.secret_key = secret_key or os.urandom(24).hex()

app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict' if _is_production else 'Lax'
app.config['SESSION_COOKIE_SECURE'] = _is_production  # Only transmit cookies over HTTPS in production
app.config['SESSION_PERMANENT'] = True
app.config.setdefault('SESSION_COOKIE_NAME', 'gateway_session')

# Additional security headers
app.config['SESSION_COOKIE_DOMAIN'] = None  # Set to your domain in production

# Register blueprints and initialize the user DB
register_blueprints(app)
init_user_db()


# Security headers middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    if _is_production:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


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
