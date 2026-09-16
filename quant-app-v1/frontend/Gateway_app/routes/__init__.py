from .dashboard import dashboard_bp
from .landing import landing_bp
from .main_app import main_bp


def register_blueprints(app):
    app.register_blueprint(landing_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(main_bp)
