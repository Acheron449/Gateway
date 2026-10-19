"""Unit tests for the short-lived cooperative job store."""
from __future__ import annotations
import asyncio
import threading
from app.services import job_store


def test_cancel_is_idempotent_and_terminal_jobs_cannot_be_cancelled():
    job_id = job_store.create("test")
    assert job_store.cancel(job_id) is True and job_store.cancel(job_id) is True
    assert job_store.is_cancelled(job_id)
    job_store.mark_cancelled(job_id)
    assert job_store.get(job_id)["status"] == "cancelled" and job_store.cancel(job_id) is False
    job_store.update(job_id, status="succeeded")
    assert job_store.get(job_id)["status"] == "cancelled"


def test_sync_worker_respects_pre_requested_cancellation():
    job_id = job_store.create("test"); called = []
    job_store.cancel(job_id)
    job_store.run_worker(job_id, lambda active_id: called.append(active_id))
    for _ in range(100):
        if job_store.get(job_id)["status"] == "cancelled": break
        threading.Event().wait(0.005)
    assert not called and job_store.get(job_id)["status"] == "cancelled"


def test_async_worker_success_remains_terminal():
    job_id = job_store.create("test")
    async def worker(active_id):
        await asyncio.sleep(0)
        job_store.update(active_id, message="finished")
    async def run():
        job_store.run_async_worker(job_id, worker)
        await asyncio.sleep(0.01)
    asyncio.run(run())
    assert job_store.get(job_id)["status"] == "succeeded" and job_store.cancel(job_id) is False
