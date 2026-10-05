#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, '/Users/ChristineC/Documents/GitHub/Gateway/quant-app-v1/backend')
try:
    from app.providers.openbb_provider import OpenBBProvider
    print("SUCCESS importing OpenBBProvider", file=sys.stderr)
    with open('/tmp/bb_result.txt', 'w') as f:
        f.write('SUCCESS')
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
    with open('/tmp/bb_result.txt', 'w') as f:
        f.write(f'ERROR: {type(e).__name__}: {e}')
EOF
python3 /Users/ChristineC/Documents/GitHub/Gateway/test_openbb.py 2>&1; echo "---"; cat /tmp/bb_result.txt 2>&1