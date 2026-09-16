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

app.secret_key = os.getenv('QUANT_FRONTEND_SECRET') or os.urandom(24).hex()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_PERMANENT'] = True
app.config.setdefault('SESSION_COOKIE_NAME', 'gateway_session')

register_blueprints(app)
init_user_db()


if __name__ == "__main__":
    app.run(debug=True, port=5000)
