"""Shared helpers for economic-calendar HTML sources (ForexFactory, Bloomberg).

Fetching uses browser-like headers and turns upstream bot challenges (Cloudflare
403 pages, captchas) into honest ``ProviderUnavailableError`` messages so the
calendar endpoint can fall back to the next source instead of failing silently.

Parsing is deliberately tolerant: rows are extracted with the stdlib
``html.parser`` (no new dependencies) and cells are matched by CSS class
fragments, so minor markup drift degrades gracefully.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import urljoin

from app.providers.base import ProviderUnavailableError

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "identity",
}

_CHALLENGE_MARKERS = (
    "Just a moment",
    "Attention Required",
    "cf-browser-verification",
    "Verify you are human",
    "checking your browser",
    "captcha",
)


def _httpx():
    """Lazy import: httpx loads on first use, not at module import time."""
    import httpx

    return httpx


async def fetch_html(url: str, *, referer: Optional[str] = None, timeout: float = 20.0) -> str:
    """GET ``url`` with browser headers; raise a described error on blockage."""
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer
    httpx = _httpx()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
    except Exception as exc:  # network/DNS/TLS failures
        raise ProviderUnavailableError(f"Request to {url} failed: {exc}") from exc

    body = response.text if response.status_code != 500 else ""
    challenged = any(marker.lower() in body[:40000].lower() for marker in _CHALLENGE_MARKERS)
    if response.status_code in (401, 403, 429) or challenged:
        raise ProviderUnavailableError(
            f"Upstream returned a bot challenge (HTTP {response.status_code}); "
            "this source blocks server-side requests",
            status_code=response.status_code,
        )
    if response.status_code >= 400:
        raise ProviderUnavailableError(
            f"Upstream returned HTTP {response.status_code}",
            status_code=response.status_code,
        )
    return response.text


class TableRow:
    """One ``<tr>``: its attributes plus parsed cells."""

    __slots__ = ("attrs", "cells")

    def __init__(self, attrs: dict[str, str]) -> None:
        self.attrs = attrs
        self.cells: list[dict[str, Any]] = []


class _RowParser(HTMLParser):
    """Collect ``<tr>`` rows with cell class/text/marks (class-bearing child tags)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[TableRow] = []
        self._row_stack: list[TableRow] = []
        self._cell_stack: list[dict[str, Any]] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = {key: (value or "") for key, value in attrs}
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag == "tr":
            row = TableRow(attr_map)
            self.rows.append(row)
            self._row_stack.append(row)
            self._cell_stack.clear()
            return
        if tag in ("td", "th"):
            if self._cell_stack:  # implicitly close an unclosed cell
                self._cell_stack.pop()
            if not self._row_stack:
                return
            cell = {"attrs": attr_map, "text": "", "marks": []}
            self._row_stack[-1].cells.append(cell)
            self._cell_stack.append(cell)
            return
        if tag == "br" and self._cell_stack:
            self._cell_stack[-1]["text"] += " "
            return
        # remember class/title-bearing descendants (impact icons, sentiment spans, links)
        if self._cell_stack and ("class" in attr_map or "title" in attr_map):
            marks = self._cell_stack[-1]["marks"]
            if len(marks) < 40:
                marks.append({"tag": tag, **attr_map})

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag == "tr":
            if self._row_stack:
                self._row_stack.pop()
            self._cell_stack.clear()
        elif tag in ("td", "th"):
            if self._cell_stack:
                self._cell_stack.pop()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in ("br", "img", "input", "hr", "meta", "link"):
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._skip or not self._cell_stack:
            return
        self._cell_stack[-1]["text"] += data


def parse_table_rows(html: str) -> list[TableRow]:
    parser = _RowParser()
    parser.feed(html)
    return parser.rows


def cell_text(cell: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(cell.get("text", ""))).strip()


def cell_with_class(row: TableRow, class_fragment: str) -> Optional[dict[str, Any]]:
    for cell in row.cells:
        if class_fragment in str(cell["attrs"].get("class", "")):
            return cell
    return None


def tz_from_env(env_name: str, default_hours: int = 2) -> timezone:
    """Fixed UTC offset for sources that render naive local timestamps.

    Defaults to UTC+2 (the classic ForexFactory/Investing display timezone and
    the offset implied by JBlanked's documented example). Override per source
    with the matching ``*_TZ_OFFSET_HOURS`` environment variable.
    """
    raw = os.getenv(env_name, str(default_hours))
    try:
        hours = int(raw)
    except ValueError:
        hours = default_hours
    return timezone(timedelta(hours=hours))


def parse_naive(text: str, formats: tuple[str, ...], tz: timezone) -> Optional[datetime]:
    """Parse a naive timestamp string and convert it to UTC."""
    cleaned = re.sub(r"\s+", " ", text.strip())
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=tz).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def to_float(value: Any) -> Optional[float]:
    """Parse provider numeric fields, treating dashes/placeholders as None."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "—", "–", "N/A", "n/a", "na", "null", "nan"}:
        return None
    text = text.replace(",", "").rstrip("%").rstrip("+").strip()
    try:
        return float(text)
    except ValueError:
        return None


def absolute(url: str, base: str) -> str:
    return urljoin(base, url.replace("&amp;", "&"))


__all__ = [
    "BROWSER_HEADERS",
    "ProviderUnavailableError",
    "TableRow",
    "absolute",
    "cell_text",
    "cell_with_class",
    "fetch_html",
    "parse_naive",
    "parse_table_rows",
    "to_float",
    "tz_from_env",
]
