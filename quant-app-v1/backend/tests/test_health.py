"""NFR-20: readiness reports real dependency state; liveness never depends on it."""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest

from app.api import main as api_main


async def _get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_main.app), base_url="http://test"
    ) as client:
        return await client.get(path)


def _broken_connection(*args, **kwargs):
    raise sqlite3.OperationalError("unable to open database file")


@pytest.mark.asyncio
async def test_health_reports_readiness_and_machine_readable_components() -> None:
    for path in ("/health", "/health/ready"):
        response = await _get(path)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "gateway-api"
        assert body["version"] == api_main.app.version
        assert body["environment"] == "local"
        assert body["execution_mode"] == "paper"
        assert body["capabilities"]["paper_execution"] is True
        assert body["capabilities"]["live_execution"] is False

        database = body["components"]["database"]
        assert database["status"] == "ok"
        assert database["detail"] is None
        assert isinstance(database["latency_ms"], float)
        assert database["latency_ms"] >= 0

        text = json.dumps(body).lower()
        for secret in ("token", "secret", "password", "authorization"):
            assert secret not in text


@pytest.mark.asyncio
async def test_health_returns_503_when_database_dependency_fails(monkeypatch) -> None:
    monkeypatch.setattr(api_main.database, "get_connection", _broken_connection)

    for path in ("/health", "/health/ready"):
        response = await _get(path)

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["components"]["database"]["status"] == "failed"
        assert body["components"]["database"]["detail"] == "database unavailable"
        assert isinstance(body["components"]["database"]["latency_ms"], float)
        assert "unable to open database file" not in json.dumps(body)


@pytest.mark.asyncio
async def test_liveness_stays_ok_while_database_is_down(monkeypatch) -> None:
    monkeypatch.setattr(api_main.database, "get_connection", _broken_connection)

    ready = await _get("/health/ready")
    live = await _get("/health/live")

    assert ready.status_code == 503
    assert live.status_code == 200
    assert live.json() == {
        "status": "ok",
        "service": "gateway-api",
        "version": api_main.app.version,
    }
