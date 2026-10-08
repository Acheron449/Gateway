"""One-click installer for the optional Kronos forecasting dependency.

Clones the upstream repository, installs its requirements into the running
interpreter, and pre-downloads the Hugging Face model artifacts. All output
goes to a log file that the status endpoint tails so the UI can show live
progress. The heavy work runs in a detached subprocess — the API never
blocks on it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

KRONOS_REPO_URL = os.getenv("KRONOS_REPO_URL", "https://github.com/shiyu-coder/Kronos.git")

_SETTINGS_DIR = Path(__file__).resolve().parents[1] / "settings"
_LOG_FILE = _SETTINGS_DIR / "kronos_install.log"
_PATH_FILE = _SETTINGS_DIR / "kronos_install_path.json"

_proc: subprocess.Popen[bytes] | None = None


class KronosInstallError(RuntimeError):
    """Raised when an install cannot be started."""


def _saved_path() -> str:
    """Directory the user picked in the installer popup (item 11)."""
    try:
        if _PATH_FILE.exists():
            return str(json.loads(_PATH_FILE.read_text(encoding="utf-8")).get("path") or "")
    except (OSError, ValueError, TypeError):
        return ""
    return ""


def repo_target() -> Path:
    env = os.getenv("KRONOS_REPO_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    saved = _saved_path().strip()
    if saved:
        return Path(saved).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "vendor" / "Kronos"


def models_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "models" / "kronos"


def _repo_ready() -> bool:
    return (repo_target() / "model").is_dir()


# Import names for vendor/Kronos/requirements.txt — checked with find_spec so
# status() stays cheap and never imports torch just to answer a poll.
_REQUIRED_MODULES = ("torch", "einops", "huggingface_hub", "safetensors", "numpy", "pandas", "tqdm")


def dependency_status() -> dict[str, bool]:
    import importlib.util

    result: dict[str, bool] = {}
    for name in _REQUIRED_MODULES:
        try:
            result[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, ModuleNotFoundError):
            result[name] = False
    return result


def _usable(repo_present: bool, deps: dict[str, bool]) -> bool:
    """"Installed"" means the model can actually be loaded, not just that the
    repository folder exists — otherwise the installer UI would never offer to
    fetch missing packages (torch & friends are large and often absent)."""
    return repo_present and all(deps.values())


def _tail(lines: int = 40) -> str:
    if not _LOG_FILE.exists():
        return ""
    try:
        text = _LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def status() -> dict[str, Any]:
    """Install progress for the UI (safe to poll)."""
    global _proc
    installing = _proc is not None and _proc.poll() is None
    exit_code = _proc.poll() if _proc is not None else None
    tokenizer = models_dir() / "Kronos-Tokenizer-base"
    model = models_dir() / "Kronos-base"
    ready = _repo_ready()
    deps = dependency_status()
    usable = _usable(ready, deps)
    return {
        "installed": usable,
        "repo_ready": ready,
        "repo_path": str(repo_target()),
        "repo_present": ready,
        "dependencies": deps,
        "missing_dependencies": sorted(name for name, ok in deps.items() if not ok),
        "models": {
            "tokenizer": tokenizer.is_dir(),
            "model": model.is_dir(),
        },
        "installing": installing,
        "exit_code": exit_code if not installing else None,
        "log_tail": _tail(),
        "log_updated": time.time() if _LOG_FILE.exists() else None,
    }


def start_install(force: bool = False, path: str | None = None) -> dict[str, Any]:
    """Kick off the detached install. Raises if one is already running.

    ``path`` is the destination the user chose in the installer popup — it is
    persisted so status() and later predictions resolve to the same checkout.
    """
    global _proc
    if _proc is not None and _proc.poll() is None:
        raise KronosInstallError("Kronos install is already running")

    target = repo_target()
    if path and path.strip():
        target = Path(path).strip().expanduser().resolve()
        try:
            _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            _PATH_FILE.write_text(
                json.dumps({"path": str(target)}, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            raise KronosInstallError(f"Could not save the install location: {exc}") from exc

    # "Already installed" only blocks a *re*-install into the very same
    # destination when the model is genuinely usable; a partial install (repo
    # present, packages missing) must always be completable without force.
    if _usable((target / "model").is_dir(), dependency_status()) and not force:
        raise KronosInstallError("Kronos is already installed (set force to reinstall)")

    models = models_dir()
    models.mkdir(parents=True, exist_ok=True)
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)

    python = sys.executable
    steps = [
        f'echo "== Cloning {KRONOS_REPO_URL} =="',
        (
            f'if [ -d "{target}/.git" ]; then echo "Repository already present — skipping clone"; '
            f'elif [ -d "{target}" ]; then echo "ERROR: {target} exists but is not a git checkout" >&2; exit 1; '
            f'else git clone --depth 1 "{KRONOS_REPO_URL}" "{target}"; fi'
        ),
        f'echo "== Installing Python requirements (this can take a few minutes) =="',
        f'"{python}" -m pip install --upgrade pip >/dev/null 2>&1 || true',
        f'if [ -f "{target}/requirements.txt" ]; then '
        f'"{python}" -m pip install -r "{target}/requirements.txt"; '
        f'else echo "No requirements.txt — skipping"; fi',
        f'echo "== Downloading Kronos model weights from Hugging Face =="',
        f'"{python}" - <<PY || echo "Model download failed (weights will fetch on first use)"',
        "from huggingface_hub import snapshot_download",
        f"snapshot_download('NeoQuasar/Kronos-Tokenizer-base', local_dir=r'{models / 'Kronos-Tokenizer-base'}')",
        f"snapshot_download('NeoQuasar/Kronos-base', local_dir=r'{models / 'Kronos-base'}')",
        "PY",
        f'echo "== Install complete =="',
    ]
    script = "#!/bin/sh\nset -e\n" + "\n".join(steps) + "\n"

    log_handle = _LOG_FILE.open("ab")
    try:
        log_handle.write(f"\n----- kronos install started {time.strftime('%Y-%m-%d %H:%M:%S')} -----\n".encode())
        log_handle.flush()
        _proc = subprocess.Popen(
            ["/bin/sh", "-c", script],
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(target.parent),
        )
    except OSError as exc:
        log_handle.close()
        raise KronosInstallError(f"Unable to start installer: {exc}") from exc
    finally:
        # The child holds its own dup'd fd; ours can close.
        try:
            log_handle.close()
        except OSError:
            pass

    return status()
