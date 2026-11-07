"""Live SSE smoke test for /llm/chat and the aggregate reply cap.

Opt-in: this needs a real provider key, so it is not part of the test suite
(the offline coverage is ``tests/test_phase2_provider_safety.py``). It mounts
the chat router without the private-data gate, streams a real completion, and
verifies that the reply is truncated exactly at ``MAX_REPLY_CHARS`` with a
terminal error event.

    cd quant-app-v1/backend
    PYTHONPATH=. ../../.venv/bin/python scripts/smoke_chat_stream.py \
        --provider openrouter --model openai/gpt-4o-mini --max-chars 400

Exit status: 0 pass, 1 check failed or provider error, 2 no usable provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "quant-app-v1" / "backend"))

try:  # The app reads provider keys from the repo-root .env.
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover - dotenv is an app dependency
    pass


def _configured_providers() -> list[dict]:
    from app.services import llm_providers

    return [entry for entry in llm_providers.list_providers() if entry.get("configured")]


def _parse_events(raw: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in raw.splitlines()
        if line.startswith("data: ")
    ]


async def _run(args: argparse.Namespace) -> int:
    from app.services import llm_providers

    if not args.provider:
        configured = _configured_providers()
        if configured:
            print("Saved providers (add a key, then pass --provider/--model):")
            for entry in configured:
                print(f"  {entry['id']}: {entry.get('base_url')} models={entry.get('models', [])[:5]}")
        else:
            print("No provider is configured.")
        print("Set a provider key (e.g. OPENROUTER_API_KEY in the repo-root .env) and rerun with --provider.")
        return 2

    try:
        llm_providers.resolve_endpoint(args.provider)
    except llm_providers.LlmError as exc:
        print(f"Provider '{args.provider}' is not usable: {exc}")
        return 2

    entry = llm_providers.canonical_provider(args.provider)
    settings = llm_providers._load_store().get(args.provider, {}) if entry else {}
    model = args.model or settings.get("default_model") or next(iter(settings.get("models") or []), None)
    if not model:
        print(f"No model given and none saved for '{args.provider}' — pass --model.")
        return 2

    from fastapi import FastAPI
    import httpx

    from app.api.v1 import llm as llm_api
    from app.auth import User, get_current_user, private_data_unavailable

    llm_api.MAX_REPLY_CHARS = args.max_chars
    ungated = FastAPI()
    ungated.include_router(llm_api.router)
    ungated.dependency_overrides[get_current_user] = lambda: User(id="smoke-user", email="smoke@local.test")
    ungated.dependency_overrides[private_data_unavailable] = lambda: None

    payload = {
        "provider": args.provider,
        "model": model,
        "max_tokens": args.max_tokens,
        "messages": [{"role": "user", "content": args.prompt}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ungated), base_url="http://smoke") as client:
        async with client.stream("POST", "/llm/chat", json=payload, timeout=120.0) as response:
            if response.status_code != 200:
                body = (await response.aread()).decode("utf-8", "replace")
                print(f"FAIL status={response.status_code}: {body[:300]}")
                return 1
            content_type = response.headers.get("content-type", "")
            raw = "".join([chunk async for chunk in response.aiter_text()])

    events = _parse_events(raw)
    deltas = [event["text"] for event in events if event.get("type") == "delta"]
    errors = [event.get("message", "") for event in events if event.get("type") == "error"]
    text = "".join(deltas)
    print(
        f"provider={args.provider} model={model} status=200 content_type={content_type} "
        f"deltas={len(deltas)} chars={len(text)} cap={args.max_chars}"
    )

    if not content_type.startswith("text/event-stream"):
        print(f"FAIL expected text/event-stream, got {content_type}")
        return 1
    if not deltas:
        print(f"FAIL no deltas streamed: {errors[-1] if errors else 'no error event'}")
        return 1
    if len(text) != args.max_chars:
        print(f"FAIL provider produced {len(text)} chars, expected the cap ({args.max_chars}); retry with a longer prompt")
        return 1
    if not events or events[-1].get("type") != "error" or "aggregate limit" not in errors[-1]:
        print("FAIL stream did not end with the aggregate-limit error")
        return 1
    print("PASS real SSE streaming truncated exactly at the cap with a terminal error")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", help="Provider id, e.g. openrouter")
    parser.add_argument("--model", help="Model id; defaults to the saved default")
    parser.add_argument("--max-chars", type=int, default=400, help="Temporary aggregate cap")
    parser.add_argument("--max-tokens", type=int, default=2048, help="Per-completion token limit (max 8192)")
    parser.add_argument(
        "--prompt",
        default="Write a long, detailed story about a lighthouse keeper. Do not stop early.",
    )
    args = parser.parse_args()
    if not 1 <= args.max_chars <= 100_000:
        parser.error("--max-chars must be between 1 and 100000")
    if not 1 <= args.max_tokens <= 8192:
        parser.error("--max-tokens must be between 1 and 8192")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
