"""Encrypted at-rest secrets vault for user API keys and tokens.

Every value is Fernet-encrypted before it touches disk; the vault file is
written atomically with 0600 permissions. The encryption key comes from
``GATEWAY_PROVIDER_KEY`` / ``GATEWAY_PROVIDER_KEY_FILE`` (same key the
provider registry uses) and, when neither is set, from a locally generated
key file kept next to the vault — so keys are never stored in plaintext
regardless of configuration.

Entries are namespaced free-form secrets (e.g. ``supabase/url``,
``cloudflare/api-token``); names and timestamps are stored in the clear so
the UI can list them, values never are.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

_SETTINGS_DIR = Path(__file__).resolve().parents[1] / "settings"
_VAULT_FILE = _SETTINGS_DIR / "secrets.vault"
_VAULT_KEY_FILE = _SETTINGS_DIR / "secrets.vault.key"


class VaultError(RuntimeError):
    """Raised when the vault cannot be read or written."""


def _ensure_dir() -> None:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def _resolve_key() -> bytes:
    """Resolve the Fernet key: env/key-file first, else a generated key file."""
    env = os.getenv("GATEWAY_PROVIDER_KEY", "").strip()
    if not env:
        key_file = os.getenv("GATEWAY_PROVIDER_KEY_FILE", "").strip()
        if key_file:
            try:
                env = Path(key_file).read_text(encoding="utf-8").strip()
            except OSError:
                env = ""
    if env:
        try:
            Fernet(env.encode("utf-8"))
            return env.encode("utf-8")
        except ValueError:
            pass  # not a valid Fernet key — fall through to the local key file

    _ensure_dir()
    if _VAULT_KEY_FILE.exists():
        try:
            raw = _VAULT_KEY_FILE.read_text(encoding="utf-8").strip().encode("utf-8")
            Fernet(raw)
            return raw
        except (OSError, ValueError):
            pass
    key = Fernet.generate_key()
    _VAULT_KEY_FILE.write_text(key.decode("ascii"), encoding="utf-8")
    try:
        _VAULT_KEY_FILE.chmod(0o600)
    except OSError:
        pass
    return key


def _load() -> dict[str, Any]:
    if not _VAULT_FILE.exists():
        return {"version": 1, "secrets": {}}
    try:
        with _VAULT_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("secrets"), dict):
            raise ValueError("malformed vault")
        return data
    except (OSError, ValueError, TypeError) as exc:
        raise VaultError(f"Secrets vault is unreadable: {exc}") from exc


def _save(data: dict[str, Any]) -> None:
    _ensure_dir()
    temporary = _VAULT_FILE.with_suffix(".vault.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, _VAULT_FILE)
    try:
        _VAULT_FILE.chmod(0o600)
    except OSError:
        pass


def _normalized(name: str) -> str:
    clean = name.strip()
    if not clean or len(clean) > 80:
        raise VaultError("Secret name must be 1-80 characters")
    return clean


def list_secrets() -> list[dict[str, Any]]:
    """Metadata only — never values."""
    data = _load()
    secrets = data["secrets"]
    return [
        {
            "name": name,
            "note": str(entry.get("note") or ""),
            "length": int(entry.get("length") or 0),
            "created_at": entry.get("created_at"),
            "updated_at": entry.get("updated_at"),
        }
        for name, entry in sorted(secrets.items())
        if isinstance(entry, dict)
    ]


def get_secret(name: str) -> str | None:
    """Decrypt and return one secret value."""
    key = _normalized(name)
    data = _load()
    entry = data["secrets"].get(key)
    if not isinstance(entry, dict):
        return None
    cipher = entry.get("cipher")
    if not isinstance(cipher, str):
        return None
    try:
        return Fernet(_resolve_key()).decrypt(cipher.encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise VaultError(f"Unable to decrypt '{key}': {exc}") from exc


def set_secret(name: str, value: str, note: str = "") -> dict[str, Any]:
    """Encrypt and persist one secret."""
    key = _normalized(name)
    plain = value.strip()
    if not plain:
        raise VaultError("Secret value must not be empty")
    data = _load()
    now = datetime.now(timezone.utc).isoformat()
    existing = data["secrets"].get(key)
    created_at = existing.get("created_at") if isinstance(existing, dict) else None
    data["secrets"][key] = {
        "cipher": Fernet(_resolve_key()).encrypt(plain.encode("utf-8")).decode("ascii"),
        "length": len(plain),
        "note": note.strip()[:200],
        "created_at": created_at or now,
        "updated_at": now,
    }
    _save(data)
    return {
        "name": key,
        "note": note.strip()[:200],
        "length": len(plain),
        "created_at": created_at or now,
        "updated_at": now,
    }


def delete_secret(name: str) -> bool:
    key = _normalized(name)
    data = _load()
    if key not in data["secrets"]:
        return False
    del data["secrets"][key]
    _save(data)
    return True
