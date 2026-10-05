"""Double-fork uvicorn so it survives the launching shell exiting.

Usage: .venv/bin/python scripts/dev_server_daemon.py [port]
"""

from __future__ import annotations

import os
import sys


def daemonize() -> None:
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        sys.exit(0)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    daemonize()
    sys.stdout.flush()

    python = sys.executable
    uvicorn_entry = os.path.join(os.path.dirname(python), "uvicorn")
    os.execv(
        uvicorn_entry,
        [
            uvicorn_entry,
            "app.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
    )


if __name__ == "__main__":
    main()
