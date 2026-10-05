# Portable Script Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository's utility scripts independent of a specific developer checkout and fixed temporary-file paths.

**Architecture:** Resolve repository-local locations from each script's `__file__`; use the OS temporary-directory API only where ephemeral isolated state is required. Leave container filesystem paths unchanged because they are part of container configuration rather than host-checkout references.

**Tech Stack:** Python standard library (`pathlib`, `tempfile`), existing backend dependencies.

**Spec:** `docs/superpowers/specs/2026-10-05-portable-script-paths-design.md`

## Global Constraints

- Do not change Docker or Compose container paths.
- Preserve a user-provided `GATEWAY_DATA_DIR`.
- `test_openbb.py` must run from any current working directory.
- Do not retain embedded shell text in a Python source file.

## Review Focus

- Invocation from a directory other than the repository root still resolves the backend import path.
- A `GATEWAY_DATA_DIR` supplied by the caller is never overwritten.
- The default verification data directory is unique to the invocation rather than shared stale state.
- A failed OpenBB import records the same error message that it writes to stderr.
- The first-party tracked-source scan finds no developer-machine or fixed temporary paths outside intentional container configuration.

---

### Task 1: Make utility scripts location-independent

**Files:**
- Modify: `test_openbb.py`
- Modify: `quant-app-v1/backend/scripts/verify_issue_fixes.py`

**Interfaces:**
- Consumes: `Path(__file__).resolve()`, `tempfile.mkdtemp()`, and existing environment variables.
- Produces: a directly runnable OpenBB import-check script and an isolated default data directory for endpoint verification.

- [ ] **Step 1: Write a failing portability check for `test_openbb.py`**

Run the script from `/tmp` using the repository Python and assert it exits successfully without the former `/Users/ChristineC/Documents/GitHub/Gateway` path.

- [ ] **Step 2: Run the check to verify it fails**

Run: `project_root="$(git rev-parse --show-toplevel)"; temp_dir="$(mktemp -d)"; cd "$temp_dir" && python3 "$project_root/test_openbb.py"`
Expected: FAIL with the current Python syntax error caused by embedded shell text, or module import failure caused by the fixed checkout path.

- [ ] **Step 3: Derive `test_openbb.py` paths from the script location**

Use `pathlib.Path(__file__).resolve().parent` to build the backend import directory and a sibling result-file path. Remove `EOF` and the embedded shell command. Preserve success/error stderr output and result-file contents.

- [ ] **Step 4: Run the portability check to verify it passes**

Run: `project_root="$(git rev-parse --show-toplevel)"; temp_dir="$(mktemp -d)"; cd "$temp_dir" && python3 "$project_root/test_openbb.py"`
Expected: PASS; the script imports `OpenBBProvider` and writes its result beside `test_openbb.py`.

- [ ] **Step 5: Replace the fixed verification data directory**

Import `tempfile` in `quant-app-v1/backend/scripts/verify_issue_fixes.py` and set the default `GATEWAY_DATA_DIR` to a newly created temporary directory, retaining `setdefault` so caller configuration wins.

- [ ] **Step 6: Verify compilation and environment override behavior**

Run: `python3 -m py_compile test_openbb.py quant-app-v1/backend/scripts/verify_issue_fixes.py`
Expected: PASS.

Run: `GATEWAY_DATA_DIR=custom-data python3 -c "import runpy; state = runpy.run_path('quant-app-v1/backend/scripts/verify_issue_fixes.py', run_name='path_check'); import os; assert os.environ['GATEWAY_DATA_DIR'] == 'custom-data'"`
Expected: PASS.

- [ ] **Step 7: Commit**

Stage `test_openbb.py` and `quant-app-v1/backend/scripts/verify_issue_fixes.py`, then commit with `fix: make utility script paths portable`.

### Task 2: Verify the repository no longer contains applicable host paths

**Files:**
- Verify: tracked first-party files, excluding dependencies, generated artifacts, and documented container configuration.

**Interfaces:**
- Consumes: `git ls-files` and the completed scripts from Task 1.
- Produces: evidence that applicable hardcoded developer and temporary paths have been removed.

- [ ] **Step 1: Scan first-party tracked sources**

Run a tracked-file scan for `/Users/`, `/tmp/`, `/home/`, `/private/`, `/var/`, `/opt/`, `/Volumes/`, `Gateway/`, and `ChristineC`, excluding dependencies and generated reports.

- [ ] **Step 2: Confirm remaining results are intentional**

Expected: only Docker/Compose container paths and historical metadata remain; no executable first-party utility script contains a developer-machine or fixed temporary path.

- [ ] **Step 3: Commit documentation artifacts**

Stage the design spec and this plan, then commit with `docs: plan portable utility paths`.
