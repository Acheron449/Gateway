"""NFR-22: optional, off-by-default error aggregation with token/email scrubbing."""

from __future__ import annotations

import json

import httpx
import pytest
from loguru import logger

from app.api import main as api_main
from app.api.error_aggregation import ErrorAggregator, scrub_error_text


def _boom() -> None:
    raise RuntimeError(
        "provider failed for user@example.com with token=abc123 and Bearer xyz789"
    )


api_main.app.add_api_route("/__test__/boom", _boom, methods=["GET"], include_in_schema=False)


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_main.app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_validation_errors_and_unknown_routes_are_machine_readable() -> None:
    invalid = await _request("POST", "/auth/login", json={})
    missing = await _request("GET", "/definitely-not-a-route")

    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], list)
    assert invalid.headers["X-Request-ID"]

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}
    assert missing.headers["X-Request-ID"]


@pytest.mark.asyncio
async def test_unhandled_exception_returns_fixed_500_envelope(monkeypatch) -> None:
    monkeypatch.setattr(api_main.error_aggregator, "enabled", False)

    response = await _request("GET", "/__test__/boom")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "request_id": response.headers["X-Request-ID"],
    }
    text = response.text
    for leaked in ("RuntimeError", "user@example.com", "abc123", "xyz789", "Traceback"):
        assert leaked not in text


@pytest.mark.asyncio
async def test_enabled_aggregation_captures_scrubbed_event(monkeypatch) -> None:
    monkeypatch.setattr(api_main.error_aggregator, "enabled", True)
    records: list[dict] = []

    def sink(message) -> None:
        event = message.record["extra"].get("error_event")
        if event:
            records.append(event)

    handler_id = logger.add(sink, level="ERROR", format="{message}")
    try:
        response = await _request("GET", "/__test__/boom")
    finally:
        logger.remove(handler_id)

    assert response.status_code == 500
    assert len(records) == 1
    event = records[0]
    assert event["error_type"] == "RuntimeError"
    assert event["path"] == "/__test__/boom"
    assert event["method"] == "GET"
    assert event["status_code"] == 500
    assert event["request_id"] == response.headers["X-Request-ID"]
    assert len(event["error_id"]) == 32

    payload = json.dumps(event)
    for leaked in ("user@example.com", "abc123", "xyz789"):
        assert leaked not in payload
    assert "[redacted-email]" in event["message"]
    assert "[redacted]" in event["message"]


@pytest.mark.asyncio
async def test_aggregation_is_off_by_default_and_emits_no_event() -> None:
    aggregator = ErrorAggregator()
    assert aggregator.enabled is False

    records: list[dict] = []

    def sink(message) -> None:
        if message.record["extra"].get("error_event"):
            records.append(message.record["extra"]["error_event"])

    handler_id = logger.add(sink, level="ERROR", format="{message}")
    try:
        response = await _request("GET", "/__test__/boom")
    finally:
        logger.remove(handler_id)

    assert response.status_code == 500
    assert records == []


def test_scrubber_removes_emails_and_credentials() -> None:
    scrubbed = scrub_error_text(
        "mail a@b.co token=supersecret api_key: key123 Bearer zzz999 password=hunter2"
    )
    for leaked in ("a@b.co", "supersecret", "key123", "zzz999", "hunter2"):
        assert leaked not in scrubbed
    assert "[redacted-email]" in scrubbed
    assert scrubbed.count("[redacted]") >= 4
