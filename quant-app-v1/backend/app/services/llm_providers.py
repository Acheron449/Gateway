"""LLM provider catalogue, encrypted key storage, and OpenAI-compatible chat.

Every provider the AI Harness can talk to — OpenRouter, Ollama (local and
cloud), OpenCode Zen, Cloudflare AI Gateway, Groq, Kilo Gateway, arbitrary
custom endpoints, plus the first-party OpenAI / Anthropic / Google Gemini
APIs — speaks the OpenAI ``/chat/completions`` wire format, either natively
or through the vendor's OpenAI-compatibility layer. One client path serves
them all; the provider catalogue below only varies base URL, key lookup,
and how the entry is presented in the UI.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx

from app.providers.registry import _decrypt_key, _encrypt_key, _encryption_key
from app.services import key_store


# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------

# group: "compatible" (OpenAI-compatible gateways/runtimes) | "foundation"
# (first-party foundation-model API keys). All of them are consumed through
# the same OpenAI-compatible client.
LLM_PROVIDER_CATALOG: list[dict[str, Any]] = [
    # --- OpenAI-compatible gateways & runtimes ---
    {
        "id": "openrouter",
        "label": "OpenRouter",
        "group": "compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "base_url_editable": True,
        "key_required": True,
        "key_env": "OPENROUTER_API_KEY",
        "docs": "https://openrouter.ai/keys",
        "detail": "Hundreds of models behind one OpenAI-compatible key",
        "placeholder": "sk-or-v1-…",
    },
    {
        "id": "ollama-local",
        "label": "Ollama (local)",
        "group": "compatible",
        "base_url": "http://localhost:11434/v1",
        "base_url_editable": True,
        "key_required": False,
        "key_env": "OLLAMA_API_KEY",
        "docs": "https://docs.ollama.com",
        "detail": "Local models on your machine · no API key needed",
        "placeholder": "optional",
    },
    {
        "id": "ollama-cloud",
        "label": "Ollama (cloud)",
        "group": "compatible",
        "base_url": "https://ollama.com/v1",
        "base_url_editable": True,
        "key_required": True,
        "key_env": "OLLAMA_API_KEY",
        "docs": "https://docs.ollama.com/api/authentication",
        "detail": "Hosted Ollama models at ollama.com · API key required",
        "placeholder": "…",
    },
    {
        "id": "opencode-zen",
        "label": "OpenCode Zen",
        "group": "compatible",
        "base_url": "https://opencode.ai/zen/v1",
        "base_url_editable": True,
        "key_required": True,
        "key_env": "OPENCODE_ZEN_API_KEY",
        "docs": "https://opencode.ai/docs/zen/",
        "detail": "Tested & verified models via the OpenCode Zen gateway",
        "placeholder": "sk-…",
    },
    {
        "id": "cloudflare-ai-gateway",
        "label": "Cloudflare AI Gateway",
        "group": "compatible",
        "base_url": "https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/openai",
        "base_url_editable": True,
        "key_required": True,
        "key_env": "CLOUDFLARE_AI_GATEWAY_API_KEY",
        "docs": "https://developers.cloudflare.com/ai-gateway/get-started/",
        "detail": "Proxy through your Cloudflare account · set your gateway URL below",
        "placeholder": "upstream provider key or gateway token",
    },
    {
        "id": "groq",
        "label": "Groq",
        "group": "compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "base_url_editable": True,
        "key_required": True,
        "key_env": "GROQ_API_KEY",
        "docs": "https://console.groq.com/keys",
        "detail": "Fast LPU inference for open models",
        "placeholder": "gsk_…",
    },
    {
        "id": "kilo-gateway",
        "label": "Kilo Gateway",
        "group": "compatible",
        "base_url": "https://api.kilo.ai/api/gateway",
        "base_url_editable": True,
        "key_required": True,
        "key_env": "KILO_API_KEY",
        "docs": "https://kilo.ai/docs/gateway",
        "detail": "Universal inference API · BYOK routing across providers",
        "placeholder": "…",
    },
    {
        "id": "custom-openai",
        "label": "Custom OpenAI-compatible",
        "group": "compatible",
        "base_url": "http://localhost:1234/v1",
        "base_url_editable": True,
        "key_required": False,
        "key_env": "OPENAI_COMPATIBLE_API_KEY",
        "docs": "",
        "detail": "vLLM, LM Studio, llama.cpp, LiteLLM, or any OpenAI-compatible server",
        "placeholder": "optional",
    },
    # --- Foundation API keys ---
    {
        "id": "openai",
        "label": "OpenAI",
        "group": "foundation",
        "base_url": "https://api.openai.com/v1",
        "base_url_editable": False,
        "key_required": True,
        "key_env": "OPENAI_API_KEY",
        "docs": "https://platform.openai.com/api-keys",
        "detail": "GPT models via the OpenAI API",
        "placeholder": "sk-…",
    },
    {
        "id": "anthropic",
        "label": "Anthropic",
        "group": "foundation",
        "base_url": "https://api.anthropic.com/v1/",
        "base_url_editable": False,
        "key_required": True,
        "key_env": "ANTHROPIC_API_KEY",
        "docs": "https://console.anthropic.com/settings/keys",
        "detail": "Claude models via Anthropic's OpenAI-compatibility layer",
        "placeholder": "sk-ant-…",
    },
    {
        "id": "gemini",
        "label": "Google Gemini",
        "group": "foundation",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "base_url_editable": False,
        "key_required": True,
        "key_env": "GEMINI_API_KEY",
        "docs": "https://aistudio.google.com/apikey",
        "detail": "Gemini models via Google's OpenAI-compatibility endpoint",
        "placeholder": "AIza…",
    },
]

CATALOG_BY_ID: dict[str, dict[str, Any]] = {entry["id"]: entry for entry in LLM_PROVIDER_CATALOG}

_BUNDLED_SETTINGS_DIR = Path(__file__).resolve().parent.parent / "settings"
_SETTINGS_DIR = _BUNDLED_SETTINGS_DIR
_SETTINGS_FILE = _SETTINGS_DIR / "llm_providers.json"

_MODELS_CACHE_TTL = 60.0
_models_cache: dict[str, tuple[float, list[str]]] = {}


class LlmError(RuntimeError):
    """Raised when an LLM provider cannot be resolved or rejects a request."""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _fallback_settings_dir() -> Path:
    """Writable location when the bundled ``app/settings`` dir is unusable.

    Vercel deployments exclude ``app/settings/`` (.vercelignore) and run on a
    read-only function filesystem, so ``mkdir`` on the bundled path raises
    ``OSError: [Errno 30] Read-only file system`` and used to 500 every
    ``/llm/providers`` request. Fall back to the configured data dir (or the
    system temp dir) — the same ephemeral-storage tradeoff the SQLite data
    dir already makes there.
    """
    data_dir = os.getenv("GATEWAY_DATA_DIR", "").strip()
    base = Path(data_dir) if data_dir else Path(tempfile.gettempdir())
    return base / "provider_settings"


def _ensure_dir() -> None:
    global _SETTINGS_DIR, _SETTINGS_FILE
    try:
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        return
    except OSError:
        pass
    # Bundled location missing and/or read-only: relocate to a writable one.
    _SETTINGS_DIR = _fallback_settings_dir()
    _SETTINGS_FILE = _SETTINGS_DIR / "llm_providers.json"
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)


def _load_store() -> dict[str, dict[str, Any]]:
    # Reads must never raise: an unusable settings store means "no saved
    # providers", so the catalogue still renders instead of 500-ing.
    local: dict[str, dict[str, Any]] = {}
    try:
        _ensure_dir()
        if _SETTINGS_FILE.exists():
            with _SETTINGS_FILE.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            local = value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        local = {}
    remote = key_store.load_with_backfill("llm", local)
    if remote is None or (not remote and local):
        # Supabase not configured (local dev/tests), unreachable, or still
        # empty after a promotion attempt: the per-instance file holds the
        # best available copy of old data.
        return local
    # Supabase is authoritative when configured: entries are rebuilt from
    # the durable row (payload = base_url/models/default_model, ciphertext
    # = api_key), so the local file's possibly stale copy never wins.
    merged: dict[str, dict[str, Any]] = {}
    for provider_id, entry in remote.items():
        if not isinstance(entry, dict):
            continue
        settings: dict[str, Any] = dict(entry.get("payload") or {})
        if entry.get("ciphertext"):
            settings["api_key"] = str(entry["ciphertext"])
        merged[provider_id] = settings
    return merged


def _save_store(store: dict[str, dict[str, Any]]) -> None:
    _ensure_dir()
    temporary = _SETTINGS_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, _SETTINGS_FILE)
    try:
        _SETTINGS_FILE.chmod(0o600)
    except OSError:
        pass


def canonical_provider(provider_id: str) -> dict[str, Any] | None:
    return CATALOG_BY_ID.get((provider_id or "").strip().casefold())


def stored_settings(provider_id: str) -> dict[str, Any]:
    entry = canonical_provider(provider_id)
    if entry is None:
        return {}
    store = _load_store()
    value = store.get(entry["id"])
    return value if isinstance(value, dict) else {}


def env_api_key(entry: dict[str, Any]) -> Optional[str]:
    env_name = entry.get("key_env")
    if not env_name:
        return None
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    # Tolerate alternate spellings (e.g. GOOGLE_API_KEY for Gemini).
    if entry["id"] == "gemini":
        alt = os.getenv("GOOGLE_API_KEY", "").strip()
        if alt:
            return alt
    return None


def stored_api_key(provider_id: str) -> Optional[str]:
    entry = canonical_provider(provider_id)
    if entry is None:
        return None
    encrypted = stored_settings(entry["id"]).get("api_key")
    if not encrypted or not isinstance(encrypted, str):
        return None
    encryption_key = _encryption_key()
    if not encryption_key:
        return None
    try:
        return _decrypt_key(encrypted, encryption_key)
    except Exception:
        return None


def resolve_endpoint(provider_id: str) -> tuple[str, Optional[str]]:
    """Return the effective (base_url, api_key) for a provider.

    Stored settings win over catalogue defaults; the API key falls back to
    the provider's environment variable when no key was saved in the UI.
    Raises LlmError for unknown providers or unresolved base URLs.
    """
    entry = canonical_provider(provider_id)
    if entry is None:
        raise LlmError(f"Unknown LLM provider '{provider_id}'")
    settings = stored_settings(entry["id"])
    base_url = (settings.get("base_url") or entry["base_url"]).strip().rstrip("/")
    if not base_url or "{" in base_url:
        raise LlmError(
            f"{entry['label']} needs a base URL — set it in Providers → AI models "
            "(e.g. https://gateway.ai.cloudflare.com/v1/<account>/<gateway>/openai)"
        )
    api_key = stored_api_key(entry["id"]) or env_api_key(entry)
    if entry["key_required"] and not api_key:
        raise LlmError(
            f"No API key configured for {entry['label']} — add one in Providers → AI models"
        )
    return base_url, api_key


def save_provider_settings(
    provider_id: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    models: Optional[list[str]] = None,
    default_model: Optional[str] = None,
) -> dict[str, Any]:
    entry = canonical_provider(provider_id)
    if entry is None:
        raise LlmError(f"Unknown LLM provider '{provider_id}'")

    store = _load_store()
    settings = store.get(entry["id"])
    settings = dict(settings) if isinstance(settings, dict) else {}

    if base_url is not None:
        value = base_url.strip().rstrip("/")
        if value:
            settings["base_url"] = value
        else:
            settings.pop("base_url", None)
    if api_key is not None:
        value = api_key.strip()
        if value:
            encryption_key = _encryption_key()
            if not encryption_key:
                raise LlmError(
                    "GATEWAY_PROVIDER_KEY (or its key file) is not set — cannot encrypt API keys"
                )
            settings["api_key"] = _encrypt_key(value, encryption_key)
        else:
            settings.pop("api_key", None)
    if models is not None:
        cleaned = [str(m).strip() for m in models if str(m).strip()]
        settings["models"] = cleaned[:50]
        if settings.get("default_model") and settings["default_model"] not in settings["models"]:
            settings["default_model"] = settings["models"][0] if settings["models"] else None
    if default_model is not None:
        settings["default_model"] = default_model.strip() or None

    if settings:
        store[entry["id"]] = settings
    else:
        store.pop(entry["id"], None)
    _persist_entry(entry["id"], settings, store)
    return settings


def delete_provider_key(provider_id: str) -> bool:
    entry = canonical_provider(provider_id)
    if entry is None:
        return False
    store = _load_store()
    settings = store.get(entry["id"])
    if not isinstance(settings, dict) or "api_key" not in settings:
        return False
    settings = dict(settings)
    settings.pop("api_key", None)
    if settings:
        store[entry["id"]] = settings
    else:
        store.pop(entry["id"], None)
    _persist_entry(entry["id"], settings, store)
    return True


def _persist_entry(provider_id: str, settings: dict[str, Any], store: dict) -> None:
    """Write one entry remote-first (Supabase), then to the local file.

    Remote write failures raise RuntimeError so the routes can answer 503
    ("not saved") instead of silently keeping the key only in ephemeral
    /tmp; local write failures raise LlmError.
    """
    ciphertext = settings.get("api_key")
    payload = {k: v for k, v in settings.items() if k != "api_key"}
    if settings:
        key_store.save(
            "llm",
            provider_id,
            ciphertext if isinstance(ciphertext, str) else None,
            payload=payload or None,
        )
    else:
        key_store.delete("llm", provider_id)
    try:
        _save_store(store)
    except OSError as exc:
        raise LlmError(f"Could not persist provider settings: {exc}") from exc


def has_usable_key(entry: dict[str, Any]) -> bool:
    if not entry["key_required"]:
        return True
    return bool(stored_api_key(entry["id"]) or env_api_key(entry))


def list_providers() -> list[dict[str, Any]]:
    """Catalogue + stored settings, never the raw key."""
    store = _load_store()
    providers: list[dict[str, Any]] = []
    for entry in LLM_PROVIDER_CATALOG:
        settings = store.get(entry["id"])
        settings = settings if isinstance(settings, dict) else {}
        has_key = has_usable_key(entry)
        base_url = (settings.get("base_url") or entry["base_url"]).strip()
        base_url_set = bool(base_url) and "{" not in base_url
        providers.append(
            {
                "id": entry["id"],
                "label": entry["label"],
                "group": entry["group"],
                "detail": entry["detail"],
                "base_url": base_url,
                "base_url_editable": entry["base_url_editable"],
                "key_required": entry["key_required"],
                "key_env": entry["key_env"],
                "docs": entry["docs"],
                "placeholder": entry["placeholder"],
                "has_key": has_key,
                "has_stored_key": bool(settings.get("api_key")),
                "configured": (has_key and base_url_set) if entry["key_required"] else base_url_set,
                "models": [str(m) for m in settings.get("models", []) if str(m).strip()],
                "default_model": settings.get("default_model") or None,
            }
        )
    return providers


def default_provider() -> str | None:
    """What the harness opens with: first provider that really has a key.

    Keyless entries (Ollama local, custom servers) only count when nothing
    with an actual API key is configured — an unconfigured localhost Ollama
    should not become the default the chat then fails against.
    """
    providers = list_providers()
    for provider in providers:
        if provider["configured"] and provider["has_stored_key"]:
            return provider["id"]
    for provider in providers:
        if provider["configured"] and provider["key_required"] and provider["has_key"]:
            return provider["id"]
    for provider in providers:
        if provider["configured"] and not provider["key_required"]:
            return provider["id"]
    return None


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP client
# ---------------------------------------------------------------------------

def _headers(api_key: Optional[str], provider_id: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if provider_id == "openrouter":
        headers.setdefault("HTTP-Referer", "http://localhost")
        headers.setdefault("X-Title", "Gateway")
    return headers


def _client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0))


def _extract_error(response: httpx.Response, body: str) -> str:
    detail = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or "")
            elif isinstance(err, str):
                detail = err
            detail = detail or str(payload.get("detail") or "")
    except Exception:
        detail = body.strip()[:300]
    if response.status_code == 401 or response.status_code == 403:
        return f"{provider_hint(response)} rejected the API key (HTTP {response.status_code}). {detail}".strip()
    if response.status_code == 404:
        return f"Endpoint not found (HTTP 404) — check the base URL. {detail}".strip()
    return f"Provider error (HTTP {response.status_code}). {detail}".strip()


def provider_hint(response: httpx.Response) -> str:
    return "The provider"


async def fetch_models(provider_id: str, *, use_cache: bool = True) -> list[str]:
    """GET {base}/models and return sorted model ids."""
    entry = canonical_provider(provider_id)
    if entry is None:
        raise LlmError(f"Unknown LLM provider '{provider_id}'")
    cached = _models_cache.get(entry["id"])
    if use_cache and cached and time.time() - cached[0] < _MODELS_CACHE_TTL:
        return cached[1]

    base_url, api_key = resolve_endpoint(entry["id"])
    async with _client(20.0) as client:
        try:
            response = await client.get(f"{base_url}/models", headers=_headers(api_key, entry["id"]))
        except httpx.HTTPError as exc:
            raise LlmError(f"Could not reach {entry['label']}: {exc}") from exc
    if response.status_code >= 400:
        raise LlmError(_extract_error(response, response.text))
    try:
        payload = response.json()
        raw = payload.get("data", []) if isinstance(payload, dict) else []
        models = sorted(
            {
                str(item.get("id")).strip()
                for item in raw
                if isinstance(item, dict) and item.get("id")
            }
        )
    except Exception as exc:
        raise LlmError(f"{entry['label']} returned an unreadable model list") from exc
    if not models:
        raise LlmError(f"{entry['label']} returned no models")
    _models_cache[entry["id"]] = (time.time(), models)
    return models


def _chat_payload(
    model: str,
    messages: list[dict[str, Any]],
    *,
    stream: bool,
    temperature: Optional[float],
    max_tokens: Optional[int],
) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages, "stream": stream}
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


async def chat_once(
    provider_id: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = 1024,
    timeout: float = 90.0,
) -> str:
    """One-shot (non-streaming) chat completion; returns the text content."""
    base_url, api_key = resolve_endpoint(provider_id)
    payload = _chat_payload(model, messages, stream=False, temperature=temperature, max_tokens=max_tokens)
    async with _client(timeout) as client:
        try:
            response = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=_headers(api_key, provider_id)
            )
        except httpx.HTTPError as exc:
            raise LlmError(f"Could not reach the model: {exc}") from exc
    if response.status_code >= 400:
        raise LlmError(_extract_error(response, response.text))
    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise LlmError("Provider returned an unreadable completion") from exc
    if content is None:
        raise LlmError("Provider returned an empty completion")
    return str(content)


async def stream_chat(
    provider_id: str,
    model: str,
    messages: list[dict[str, Any]],
    *,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 300.0,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat completion, yielding event dicts:
    {"type": "delta", "text": …} zero or more times, then exactly one
    {"type": "done", "usage": …} or {"type": "error", "message": …}.
    """
    base_url, api_key = resolve_endpoint(provider_id)
    payload = _chat_payload(model, messages, stream=True, temperature=temperature, max_tokens=max_tokens)

    try:
        async with _client(timeout) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                json=payload,
                headers=_headers(api_key, provider_id),
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    yield {"type": "error", "message": _extract_error(response, body)}
                    return
                usage: dict[str, Any] | None = None
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(chunk.get("usage"), dict):
                        usage = chunk["usage"]
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0] or {}
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if not text:
                        message = choice.get("message") or {}
                        text = message.get("content")
                    if text:
                        yield {"type": "delta", "text": str(text)}
                yield {"type": "done", "usage": usage}
    except LlmError as exc:
        yield {"type": "error", "message": str(exc)}
    except httpx.HTTPError as exc:
        yield {"type": "error", "message": f"Could not reach the model: {exc}"}


async def test_provider(provider_id: str, model: Optional[str] = None) -> dict[str, Any]:
    """Probe a provider with a tiny completion; returns a UI-friendly result."""
    entry = canonical_provider(provider_id)
    if entry is None:
        raise LlmError(f"Unknown LLM provider '{provider_id}'")
    settings = stored_settings(entry["id"])
    chosen = model or settings.get("default_model")
    if not chosen:
        try:
            models = await fetch_models(entry["id"], use_cache=False)
            chosen = models[0]
        except LlmError as exc:
            return {"success": False, "message": str(exc), "model": None}
        if not chosen:
            return {"success": False, "message": "No model available on this endpoint", "model": None}
    try:
        reply = await chat_once(
            entry["id"],
            chosen,
            [{"role": "user", "content": "Reply with the single word: ok"}],
            max_tokens=16,
            timeout=30.0,
        )
    except LlmError as exc:
        return {"success": False, "message": str(exc), "model": chosen}
    return {
        "success": True,
        "message": f"Connected — {chosen} replied “{reply.strip()[:40]}”",
        "model": chosen,
    }
