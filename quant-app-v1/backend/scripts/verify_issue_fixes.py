"""Verify the new backend endpoints for the 11-issue frontend pass.

Run from repo root with the local venv (uvicorn thread on :8123 + httpx,
because TestClient is broken with this starlette/httpx pairing):

  JWT_SECRET_KEY=test-secret .venv/bin/python \
      quant-app-v1/backend/scripts/verify_issue_fixes.py
"""

from __future__ import annotations

import os
import threading
import time

import httpx
import uvicorn

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("GATEWAY_DATA_DIR", "/tmp/gateway-verify-data")
from cryptography.fernet import Fernet  # noqa: E402
os.environ.setdefault("GATEWAY_PROVIDER_KEY", Fernet.generate_key().decode())

from app.api.main import app  # noqa: E402  (env must be set first)


def main() -> None:
    config = uvicorn.Config(app, host="127.0.0.1", port=8123, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    for _ in range(60):
        if server.started:
            break
        time.sleep(0.25)
    else:
        raise SystemExit("uvicorn did not start")

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}{(' — ' + detail) if detail else ''}")
        if not ok:
            failures.append(name)

    base = "http://127.0.0.1:8123"
    origin = "http://localhost:3000"

    with httpx.Client(base_url=base, timeout=60.0) as client:
        # 1) Providers list is public read, protected write (issue #2).
        r = client.get("/settings/providers", headers={"Origin": origin})
        check(
            "GET /settings/providers public + CORS",
            r.status_code == 200 and r.headers.get("access-control-allow-origin") == origin,
            f"{r.status_code}, ACAO={r.headers.get('access-control-allow-origin')}",
        )
        providers = r.json() if r.status_code == 200 else []
        check("providers payload shape", isinstance(providers, list) and len(providers) >= 1, f"{len(providers)} providers")

        finnhub = next((p for p in providers if p["name"] == "Finnhub"), None)
        if finnhub:
            r = client.post(
                "/settings/providers/Finnhub/key",
                json={"api_key": "x" * 10},
                headers={"Origin": origin},
            )
            check(
                "POST key without token -> 401 (issue #2)",
                r.status_code == 401,
                f"{r.status_code} {r.text[:80]}",
            )

        # 2) Register a user, then key save/delete works (issues #1/#3 chain).
        email = f"verify_{int(time.time())}@example.com"
        r = client.post("/auth/register", json={"email": email, "password": "password123", "name": "Verify"})
        check("register returns token", r.status_code == 200 and "access_token" in r.json(), f"{r.status_code}")
        token = r.json().get("access_token", "") if r.status_code == 200 else ""
        auth = {"Authorization": f"Bearer {token}"} if token else {}

        if token and finnhub:
            r = client.post(
                "/settings/providers/Finnhub/key",
                json={"api_key": "verify-key-123"},
                headers={**auth, "Origin": origin},
            )
            check("POST key with token -> stored", r.status_code == 200 and r.json().get("stored") is True, f"{r.status_code} {r.text[:80]}")
            r = client.get("/settings/providers", headers=auth)
            fh = next((p for p in r.json() if p["name"] == "Finnhub"), {})
            check("has_stored_key true after save", fh.get("has_stored_key") is True)
            r = client.delete("/settings/providers/Finnhub/key", headers=auth)
            check("DELETE key with token", r.status_code == 200, f"{r.status_code}")

        # 3) History fallback (issue #5) — no Alpaca creds in this env.
        r = client.get("/history/AAPL?tf=1h&limit=100", headers={"Origin": origin})
        ok = r.status_code == 200
        rows = r.json() if ok else []
        first = rows[0] if rows else {}
        sources = {row.get("source") for row in rows}
        check(
            "GET /history AAPL (yfinance fallback)",
            ok and len(rows) > 50 and sources == {"yfinance"} and first.get("volume") is not None,
            f"{r.status_code}, {len(rows)} bars, sources={sources}, vol={first.get('volume')}",
        )
        r = client.get("/history/AAPL?tf=1d&limit=100")
        check("GET /history tf=1d", r.status_code == 200 and len(r.json()) > 50, f"{r.status_code}, {len(r.json()) if r.status_code == 200 else 0} bars")

        # 4) Batch quotes (issue #9).
        r = client.get("/quotes?symbols=AAPL,MSFT,SPY", headers={"Origin": origin})
        quotes = r.json().get("quotes", []) if r.status_code == 200 else []
        check(
            "GET /quotes batch",
            r.status_code == 200 and len(quotes) >= 2 and all("change_pct" in q for q in quotes),
            f"{r.status_code}, {len(quotes)} quotes",
        )

        # 5) CORS preflight still healthy (regression guard).
        r = client.options(
            "/settings/providers",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"},
        )
        check("OPTIONS preflight", r.status_code == 200 and r.headers.get("access-control-allow-origin") == origin, f"{r.status_code}")

    server.should_exit = True
    thread.join(timeout=10)
    print()
    if failures:
        raise SystemExit(f"{len(failures)} failing checks: {failures}")
    print("All checks passed.")


if __name__ == "__main__":
    main()
