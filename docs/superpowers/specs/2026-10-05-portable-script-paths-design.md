# Portable Script Paths Design

## Goal

Make repository utility scripts runnable from any checkout location by removing developer-machine and fixed temporary filesystem paths.

## Scope

- `test_openbb.py` derives the backend directory and result-file location from its own file location.
- `quant-app-v1/backend/scripts/verify_issue_fixes.py` obtains its isolated data directory from the operating system's temporary-directory facility rather than a fixed `/tmp` path.
- The invalid shell-text fragment embedded in `test_openbb.py` is removed.

## Non-goals

Container-internal paths in Dockerfiles and Compose configuration remain unchanged: they describe the container filesystem rather than a developer checkout. Historical metadata and generated dependency artifacts are also out of scope.

## Design

`test_openbb.py` will use `pathlib.Path(__file__).resolve()` to locate the repository root and add `quant-app-v1/backend` to `sys.path`. Its result file will be a sibling of the script, keeping its output predictable and checkout-local. The script will continue to print import status and record the same success/error text.

The backend verification script will use `tempfile.mkdtemp()` for its default `GATEWAY_DATA_DIR`, preserving the caller's explicit environment value through `setdefault`. This removes the hardcoded host path while preserving each invocation's isolated state.

## Verification

- Compile both scripts with Python.
- Run `test_openbb.py` and verify it imports without relying on the old checkout path.
- Rescan tracked, first-party source files and confirm no developer-machine or fixed temporary paths remain outside documented container configuration.
