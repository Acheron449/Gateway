"""Phase 0 increment 3 — application-boundary guard (offline static scan).

Gateway ships two independent application surfaces that must never couple:

* ``backend/app``                        — the FastAPI product backend (``app.main:app``), and
* ``frontend/Gateway_app``               — the legacy Flask "Gateway_app" prototype.

Boundary rules (enforced with AST + source-line scans only; nothing is imported,
so nothing here touches ``users.db``, the Flask session store, or the network):

1. The FastAPI backend never imports Flask (``flask``, ``flask_session``) or the
   legacy ``Gateway_app`` package.
2. The legacy Flask surface never imports the FastAPI backend package.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "app"
LEGACY_ROOT = Path(__file__).resolve().parents[3] / "frontend" / "Gateway_app"

LEGACY_PACKAGE = "Gateway_app"
FLASK_MODULES = {"flask", "flask_session"}
BACKEND_TOP_LEVEL = {"app", "backend"}


def _py_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*.py")
        if "__pycache__" not in p.parts and "site-packages" not in p.parts
    )


def _imports(path: Path) -> list[str]:
    """Module names referenced by import statements in ``path`` (AST; no imports)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _head(name: str) -> str:
    return name.split(".")[0]


def _is_legacy(name: str) -> bool:
    return name == LEGACY_PACKAGE or name.startswith(LEGACY_PACKAGE + ".")


def test_backend_never_imports_flask_or_legacy() -> None:
    offenders: list[str] = []
    for path in _py_files(BACKEND_ROOT):
        rel = str(path.relative_to(BACKEND_ROOT))
        for name in _imports(path):
            if _head(name) in FLASK_MODULES or _is_legacy(name):
                offenders.append(f"{rel}: imports {name}")
    assert not offenders, (
        "Boundary breach: FastAPI backend imports Flask or legacy Gateway_app:\n"
        + "\n".join(offenders)
    )


def test_legacy_never_imports_fastapi_backend() -> None:
    offenders: list[str] = []
    for path in _py_files(LEGACY_ROOT):
        rel = str(path.relative_to(LEGACY_ROOT))
        for name in _imports(path):
            if _head(name) in BACKEND_TOP_LEVEL:
                offenders.append(f"{rel}: imports {name}")
    assert not offenders, (
        "Boundary breach: legacy Gateway_app imports the FastAPI backend:\n"
        + "\n".join(offenders)
    )
