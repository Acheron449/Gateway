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
_CANCEL_EVENTS: dict[str, threading.Event] = {}
_MAX_JOBS = 100
_MAX_AGE_SECONDS = 3600.0
TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def _prune_locked(now: float) -> None:
    expired = [job_id for job_id, job in _JOBS.items() if now - job["updated_at"] > _MAX_AGE_SECONDS]
    for job_id in expired:
        _JOBS.pop(job_id, None)
        _CANCEL_EVENTS.pop(job_id, None)
    if len(_JOBS) <= _MAX_JOBS:
        return
    ordered = sorted(_JOBS.items(), key=lambda item: item[1]["updated_at"])
    for job_id, job in ordered:
        if len(_JOBS) <= _MAX_JOBS:
            break
        if job["status"] == "running":
            continue
        _JOBS.pop(job_id, None)
        _CANCEL_EVENTS.pop(job_id, None)


def create(kind: str, meta: dict[str, Any] | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with _LOCK:
        _prune_locked(now)
        _CANCEL_EVENTS[job_id] = threading.Event()
        _JOBS[job_id] = {"id": job_id, "kind": kind, "status": "queued", "progress": 0.0, "message": "Queued", "meta": dict(meta or {}), "result": None, "error": None, "created_at": now, "updated_at": now}
    return job_id


def update(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["status"] in TERMINAL_STATUSES:
            return
        if _CANCEL_EVENTS.get(job_id) and _CANCEL_EVENTS[job_id].is_set():
            job.update(status="cancelled", message="Cancelled", updated_at=time.time())
            return
        allowed = {"status", "progress", "message", "result", "error", "meta", "iteration", "iterations", "model_calls", "max_model_calls"}
        for key, value in fields.items():
            if key in allowed:
                job[key] = value
        job["updated_at"] = time.time()


def cancel(job_id: str) -> bool:
    """Request cooperative cancellation; repeated requests are harmless."""
    with _LOCK:
        job = _JOBS.get(job_id); event = _CANCEL_EVENTS.get(job_id)
        if job is None or event is None or job["status"] in TERMINAL_STATUSES:
            return False
        event.set()
        job["cancel_requested"] = True
        job["message"] = "Cancellation requested"
        job["updated_at"] = time.time()
        return True


def is_cancelled(job_id: str) -> bool:
    with _LOCK:
        event = _CANCEL_EVENTS.get(job_id)
        return bool(event and event.is_set())


def mark_cancelled(job_id: str, message: str = "Cancelled") -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None or job["status"] in TERMINAL_STATUSES:
            return
        job.update(status="cancelled", message=message, updated_at=time.time())


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
    def guarded() -> None:
        try:
            if is_cancelled(job_id):
                mark_cancelled(job_id)
                return
            update(job_id, status="running", progress=0.05, message="Started")
            worker(job_id)
            job = get(job_id)
            if job and job["status"] not in TERMINAL_STATUSES:
                update(job_id, status="succeeded", progress=1.0, message="Done")
        except Exception as exc:  # noqa: BLE001 - job failures surface to the UI
            if is_cancelled(job_id):
                mark_cancelled(job_id)
                return
            update(
                job_id,
                status="failed",
                error=str(exc) or exc.__class__.__name__,
                message=f"Failed: {str(exc) or exc.__class__.__name__}",
            )
    threading.Thread(target=guarded, name=f"job-{job_id}", daemon=True).start()


def run_async_worker(job_id: str, worker) -> None:
    """Run ``await worker(job_id)`` as an asyncio task with status bookkeeping."""
    async def guarded() -> None:
        try:
            if is_cancelled(job_id):
                mark_cancelled(job_id)
                return
            update(job_id, status="running", progress=0.05, message="Started")
            await worker(job_id)
            job = get(job_id)
            if job and job["status"] not in TERMINAL_STATUSES:
                update(job_id, status="succeeded", progress=1.0, message="Done")
        except asyncio.CancelledError:
            if is_cancelled(job_id): mark_cancelled(job_id)
            else:
                update(job_id, status="failed", error="Cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001 - job failures surface to the UI
            if is_cancelled(job_id):
                mark_cancelled(job_id)
                return
            update(
                job_id,
                status="failed",
                error=str(exc) or exc.__class__.__name__,
                message=f"Failed: {str(exc) or exc.__class__.__name__}",
            )
    asyncio.create_task(guarded())
