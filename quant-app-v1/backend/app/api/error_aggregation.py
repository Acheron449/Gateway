"""Optional error aggregation (NFR-22).

Off by default. When ``ERROR_AGGREGATION_ENABLED`` is truthy, unhandled
server errors are emitted as one structured record with a stable event id so
a log aggregator can group them. The exception message is scrubbed of email
addresses, bearer tokens and token/key/password assignments before it leaves
the process; headers and request bodies are never part of an event.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import asdict, dataclass

from loguru import logger
from starlette.requests import Request

_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_SECRET_RE = re.compile(
    r"(?i)\b(bearer|token|api[_-]?key|apikey|secret|password|authorization)\b"
    r"(\s*[:=]\s*|\s+)([^\s,;'\"]{4,})"
)
_MAX_MESSAGE_CHARS = 500


def scrub_error_text(text: str) -> str:
    """Remove emails and credential-shaped values from free-form error text."""
    scrubbed = _EMAIL_RE.sub("[redacted-email]", text)
    scrubbed = _SECRET_RE.sub(r"\1\2[redacted]", scrubbed)
    return scrubbed[:_MAX_MESSAGE_CHARS]


@dataclass(frozen=True)
class ErrorEvent:
    error_id: str
    error_type: str
    message: str
    request_id: str | None
    method: str
    path: str
    status_code: int


class ErrorAggregator:
    """Collect unhandled server errors into a single, scrubbed event stream."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    @classmethod
    def from_env(cls) -> "ErrorAggregator":
        raw = os.getenv("ERROR_AGGREGATION_ENABLED", "").strip().lower()
        return cls(enabled=raw in {"1", "true", "yes", "on"})

    def capture(self, request: Request, exc: Exception, *, status_code: int = 500) -> ErrorEvent | None:
        if not self.enabled:
            return None
        event = ErrorEvent(
            error_id=uuid.uuid4().hex,
            error_type=type(exc).__name__,
            message=scrub_error_text(f"{type(exc).__name__}: {exc}"),
            request_id=getattr(request.state, "request_id", None),
            method=request.method,
            path=request.url.path,
            status_code=status_code,
        )
        logger.bind(error_event=asdict(event)).error("aggregated_error")
        return event
