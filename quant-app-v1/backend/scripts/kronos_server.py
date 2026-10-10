#!/usr/bin/env python3
"""Localhost Kronos inference server (item 12).

Runs the Kronos model out-of-process so the Gateway API can predict against it
over HTTP instead of loading the weights into every worker. The site talks to
it via ``KRONOS_SERVER_URL`` (default ``http://127.0.0.1:8765``).

Endpoints
---------
GET  /health   -> {"status": "ok", ...}
POST /predict  -> {"forecast": [{"index": "...", "open": ..., ...}, ...]}

Usage
-----
    python scripts/kronos_server.py [--host 127.0.0.1] [--port 8765]

Only ever binds to loopback by default: this is a local convenience server,
not a public API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Make `app.*` importable when the script is run from anywhere.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Never let forecast() probe this process as "the local server".
os.environ.setdefault("KRONOS_LOCAL_SERVER", "0")

MAX_BODY = 8 * 1024 * 1024  # 8 MiB of candles is plenty for a chart


class _Handler(BaseHTTPRequestHandler):
    server_version = "KronosLocal/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stderr.write("[kronos-server] " + (fmt % args) + "\n")

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("", "/health"):
            self._send(200, {"status": "ok", "service": "kronos-local"})
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/predict":
            self._send(404, {"detail": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send(413 if length > MAX_BODY else 400, {"detail": "missing or oversized body"})
            return
        try:
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            self._send(400, {"detail": f"invalid JSON: {exc}"})
            return

        bars = payload.get("bars") or []
        try:
            horizon = int(payload.get("horizon", 20))
            frequency = str(payload.get("frequency", "D"))
            sample_count = int(payload.get("sample_count", 1))
        except (TypeError, ValueError) as exc:
            self._send(422, {"detail": f"invalid parameters: {exc}"})
            return

        try:
            from app.services import kronos_service

            frame = kronos_service.forecast_in_process(bars, horizon, frequency, sample_count)
        except Exception as exc:  # noqa: BLE001 — report the model's own message
            self._send(503, {"detail": str(exc)})
            return

        records = frame.reset_index()
        # Name the date column `index` so clients can rely on it.
        if records.columns[0] != "index":
            records = records.rename(columns={records.columns[0]: "index"})
        records["index"] = records["index"].astype(str)
        self._send(200, {"provider": "kronos-local", "forecast": records.to_dict(orient="records")})


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Kronos inference server")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (loopback by default)")
    parser.add_argument("--port", type=int, default=8765, help="listen port")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"Kronos local server listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
