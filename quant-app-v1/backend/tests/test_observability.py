"""NFR-21: structured request logging with request ids and no secret leakage."""

from __future__ import annotations

import json
import re

import httpx
import pytest
from loguru import logger

from app.api import main as api_main
from app.api.observability import REQUEST_ID_HEADER, request_id_from


def _capture_records():
    records: list[dict] = []

    def sink(message) -> None:
        if message.record["extra"].get("request_id"):
            records.append(message.record)

    handler_id = logger.add(sink, level="INFO", format="{message}")
    return records, handler_id


async def _get(path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_main.app), base_url="http://test"
    ) as client:
        return await client.get(path, headers=headers)


@pytest.mark.asyncio
async def test_request_log_records_structured_fields_and_echoes_valid_id() -> None:
    records, handler_id = _capture_records()
    try:
        response = await _get("/health", headers={REQUEST_ID_HEADER: "client-request-1234"})
    finally:
        logger.remove(handler_id)

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "client-request-1234"
    assert len(records) == 1

    extra = records[0]["extra"]
    assert extra["request_id"] == "client-request-1234"
    assert extra["method"] == "GET"
    assert extra["path"] == "/health"
    assert extra["status"] == 200
    assert isinstance(extra["duration_ms"], float) and extra["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_request_log_replaces_unsafe_request_id() -> None:
    records, handler_id = _capture_records()
    try:
        response = await _get("/health", headers={REQUEST_ID_HEADER: "bad id!"})
    finally:
        logger.remove(handler_id)

    issued = response.headers[REQUEST_ID_HEADER]
    assert issued != "bad id!"
    assert re.fullmatch(r"[0-9a-f]{32}", issued)
    assert records[0]["extra"]["request_id"] == issued


@pytest.mark.asyncio
async def test_request_log_never_records_authorization_or_query_values() -> None:
    records, handler_id = _capture_records()
    try:
        response = await _get(
            "/definitely-not-a-route?token=supersecret&email=user@example.com",
            headers={"Authorization": "Bearer supersecret-token"},
        )
    finally:
        logger.remove(handler_id)

    assert response.status_code == 404
    assert len(records) == 1
    record = records[0]
    payload = json.dumps(record["extra"], default=str) + record["message"]

    assert record["extra"]["status"] == 404
    assert record["extra"]["path"] == "/definitely-not-a-route"
    for secret in ("supersecret", "supersecret-token", "user@example.com", "Bearer"):
        assert secret not in payload


def test_request_id_validator_bounds_length_and_charset() -> None:
    assert request_id_from("trace-12345678") == "trace-12345678"
    assert request_id_from("short") != "short"
    assert request_id_from("x" * 65) != "x" * 65
    assert request_id_from("with space") != "with space"
    assert len(request_id_from(None)) == 32
