#!/usr/bin/env python3
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPOSITORY_ROOT / "quant-app-v1" / "backend"
RESULT_PATH = REPOSITORY_ROOT / "bb_result.txt"

sys.path.insert(0, str(BACKEND_DIR))

try:
    from app.providers.openbb_provider import OpenBBProvider

    print("SUCCESS importing OpenBBProvider", file=sys.stderr)
    with RESULT_PATH.open("w") as f:
        f.write('SUCCESS')
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
    with RESULT_PATH.open("w") as f:
        f.write(f'ERROR: {type(e).__name__}: {e}')
