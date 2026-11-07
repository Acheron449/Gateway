"""Shared rate limiter for the API.

Defaults are deliberately generous: the dashboard polls several endpoints per
view change, and a tight per-IP budget reads as random "Failed to fetch"
errors in the UI. Sensitive endpoints (authentication) add stricter route
limits on top of these defaults.

The limiter lives in its own module so routers can import it without creating
a circular dependency on ``app.api.main``.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

DEFAULT_LIMITS = ("240/minute", "3000/hour")

limiter = Limiter(key_func=get_remote_address, default_limits=list(DEFAULT_LIMITS))
