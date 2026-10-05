"""In-memory job store for long-running agentic work (backtests, agent runs).

Jobs are short-lived process state: the UI polls ``GET`` for progress and
result, and entries are pruned by age/size. Nothing here is persisted —
completed lab runs live in the lab's own storage.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from typing import Any

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}
_MAX_JOBS = 100
_MAX_AGE_SECONDS = 3600.0

TERMINAL_STATUSES = ("succeeded", "failed")


def _prune_locked(now: float) -> None:
    expired = [job_id for job_id, job in _JOBS.items() if now - job["updated_at"] > _MAX_AGE_SECONDS]
    for job_id in expired:
        _JOBS.pop(job_id, None)
    if len(_JOBS) <= _MAX_JOBS:
        return
    # Drop the oldest non-running jobs first, then the oldest overall.
    ordered = sorted(_JOBS.items(), key=lambda item: item[1]["updated_at"])
    for job_id, job in ordered:
        if len(_JOBS) <= _MAX_JOBS:
            break
        if job["status"] == "running":
            continue
        _JOBS.pop(job_id, None)


def create(kind: str, meta: dict[str, Any] | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "progress": 0.0,
            "message": "Queued",
            "meta": dict(meta or {}),
            "result": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
    return job_id


def update(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        for key, value in fields.items():
            if key in ("status", "progress", "message", "result", "error", "meta"):
                job[key] = value
        job["updated_at"] = time.time()


def get(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs(kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    with _LOCK:
        jobs = [dict(job) for job in _JOBS.values() if kind is None or job["kind"] == kind]
    jobs.sort(key=lambda job: job["created_at"], reverse=True)
    return jobs[:limit]


def run_worker(job_id: str, worker) -> None:
    """Run ``worker(job_id)`` on a daemon thread with status bookkeeping."""

    def _guarded() -> None:
        try:
            update(job_id, status="running", progress=0.05, message="Started")
            worker(job_id)
            job = get(job_id)
            if job and job["status"] not in TERMINAL_STATUSES:
                update(job_id, status="succeeded", progress=1.0, message="Done")
        except Exception as exc:  # noqa: BLE001 - job failures surface to the UI
            update(
                job_id,
                status="failed",
                error=str(exc) or exc.__class__.__name__,
                message=f"Failed: {str(exc) or exc.__class__.__name__}",
            )

    threading.Thread(target=_guarded, name=f"job-{job_id}", daemon=True).start()


def run_async_worker(job_id: str, worker) -> None:
    """Run ``await worker(job_id)`` as an asyncio task with status bookkeeping."""

    async def _guarded() -> None:
        try:
            update(job_id, status="running", progress=0.05, message="Started")
            await worker(job_id)
            job = get(job_id)
            if job and job["status"] not in TERMINAL_STATUSES:
                update(job_id, status="succeeded", progress=1.0, message="Done")
        except asyncio.CancelledError:
            update(job_id, status="failed", error="Cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001 - job failures surface to the UI
            update(
                job_id,
                status="failed",
                error=str(exc) or exc.__class__.__name__,
                message=f"Failed: {str(exc) or exc.__class__.__name__}",
            )

    asyncio.create_task(_guarded())
