# Phase 0 increment 3 — application boundary (docs, offline)

## User outcome

Running Gateway locally means **one** product: the React/Vite frontend talking
to the FastAPI backend (`backend/app`). The legacy Flask "Gateway_app"
prototype is an independent, frozen surface kept only for reference — and the
two must never coupleholisticly: no shared imports, no shared runtime, no shared
database.

## What changed

- Added an **application-boundary guard test** (`backend/tests/test_phase0_boundary.py`).
  It is a static AST + source-line scan that never imports the target packages, so
  it touches neither `users.db` nor the Flask session store nor the network — it runs
  offline in CI. It enforces two rules:

  1. The FastAPI backend never imports Flask, `flask_session`, or the legacy
     `Gateway_app` package, and
  2. The legacy Flask surface never imports the FastAPI backend.

- Documented the boundary, the ownership map, and the exact startup + migration
  ownership contract.

## Boundary contract

| Surface | Runtime | Role | Start |
| --- | --- | --- | --- |
| `backend/app` | FastAPI (ASGI) | Product backend: `/catalogue`, `/stocks/{ticker}/metadata`, `/history`, `/health` | `cd quant-app-v1/backend && PYTHONPATH=. uvicorn app.main:app --reload --port 8000` |
| `frontend` (React/Vite) | Node 20 / Vite | Product UI (scanner, chart, news terminal) | `cd quant-app-v1/frontend && npm install && npm run dev` (:5173, proxies to :8000) |
| `frontend/Gateway_app` | Flask (legacy) | Frozen prototype: landing/dashboard/auth prototype | reference only — never the product surface |

Migration ownership: new feature work lands in the React/FastAPI product. The
legacy Flask `Gateway_app` is read-only reference material; it must never be
extended with new features or tied into the product backend.

## Tests

`backend/tests/test_phase0_boundary.py` — 2 offline static-scan guard tests (both
directions of the boundary).

Phase 0 increment 3 verification (from `backend/`, offline):

```sh
PYTHONPATH=. ../.venv/bin/python -m pytest tests/test_phase0_catalogue.py tests/test_phase0_safety.py tests/test_phase0_boundary.py -q
```
