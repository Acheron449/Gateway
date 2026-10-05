"""Shared pytest environment for the Gateway backend suite.

``app.auth`` fails closed at import time when ``JWT_SECRET_KEY`` is absent —
deliberate production behaviour that must not be weakened. The suite supplies
a test-only secret here (before any test module is collected) so runs work in
CI and locally without requiring the caller to export one. An explicitly
provided key always wins.
"""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
