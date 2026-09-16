from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

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
