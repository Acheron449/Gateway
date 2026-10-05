from __future__ import annotations
import sys
import os

# Explicitly force the application directories into Python's lookup path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)


from pathlib import Path

from flask import Flask, session, jsonify

from common import init_user_db

from routes import dashboard_bp, landing_bp, main_bp, register_blueprints

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

# --- NEW: Integration point for backtest submission (Client-side simulation) ---
@app.route('/api/v1/backtest/run', methods=['POST'])
def run_backtest():
    if not session.get('user_id'):
        return jsonify({"error": "Authentication required"}), 401
    # In a real app, you would pass all form data to the backend queueing service.
    # For now, we simulate queuing and return a job ID.
    job_id = "simulated_job_123"
    print(f"Received request to run backtest. Queuing job with ID: {job_id}")
    return jsonify({"status": "queued", "job_id": job_id}), 202 # 202 Accepted signals task accepted for processing

@app.route('/api/v1/backtest/<job_id>/status', methods=['GET'])
def check_status(job_id):
    # In a real app, this would poll a backend job processor.
    # We simulate the states: QUEUED, RUNNING, SUCCESS, FAILURE.
    # Since this is frontend code, we return success after one check for testing.
    if job_id == "simulated_job_123":
        # Simulate success after the first check for testing flow
        return jsonify({"status": "SUCCESS", "result": "Backtest completed successfully! Data available for download."})
    return jsonify({"status": "NOT_FOUND"}), 404

# --- End of new simulation routes ---


if __name__ == "__main__":
    app.run(debug=True, port=5000)
