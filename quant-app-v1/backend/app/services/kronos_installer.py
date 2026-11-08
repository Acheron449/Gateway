"""Fail-closed runtime installer compatibility interface for Kronos.

Kronos dependencies must be installed by the deployment/build process. Runtime
installation is intentionally unavailable to prevent API-triggered code and
environment mutation.
"""

from __future__ import annotations

from typing import Any


class KronosInstallError(RuntimeError):
    """Raised when a runtime install is rejected."""


def status() -> dict[str, Any]:
    """Return a stable, sanitized status without inspecting filesystem paths."""
    return {
        "enabled": False,
        "installed": False,
        "installing": False,
        "status": "disabled",
        "log_tail": "",
    }


def start_install(force: bool = False, path: str | None = None) -> dict[str, Any]:
    """Reject all runtime installation requests regardless of caller options."""
    del force, path
    raise KronosInstallError("Kronos runtime installation is disabled")
