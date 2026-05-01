"""
ASGI entry re-export — run::

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Historical and live endpoints live in ``app.api.main``.
"""

from app.api.main import app

__all__ = ["app"]
