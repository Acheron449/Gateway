"""Structured HTTP request logging (NFR-21).

One record per request with a request id, method, path, status and duration.
Headers, query strings and bodies are deliberately never recorded, so bearer
tokens, provider keys and email addresses cannot leak through access logs.
"""

from __future__ import annotations

import re
import time
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# A client-supplied id is echoed only when it is bounded and header-safe;
# anything else (including newlines or oversized values) is replaced.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
REQUEST_ID_HEADER = "X-Request-ID"


def request_id_from(value: str | None) -> str:
    candidate = (value or "").strip()
    if _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Stamp a request id on the response and emit one scrubbed log record."""

    async def dispatch(self, request: Request, call_next):
        request_id = request_id_from(request.headers.get(REQUEST_ID_HEADER.lower()))
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self._log(request, request_id, 500, started)
            raise
        response.headers[REQUEST_ID_HEADER] = request_id
        self._log(request, request_id, response.status_code, started)
        return response

    @staticmethod
    def _log(request: Request, request_id: str, status: int, started: float) -> None:
        logger.bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status=status,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        ).info("http_request")
