"""AI model providers, the chat harness stream, and the market context feeder.

Endpoints
---------
- ``GET/PUT/DELETE /llm/providers…`` — OpenAI-compatible + foundation-key
  configuration (encrypted keys, base URLs, model lists, connection test).
- ``POST /llm/chat`` — Server-Sent Events chat with the chosen provider.
- ``GET /llm/context`` — context feeder: assembles market data (quote,
  candles, indicators, news, calendar, portfolio, analysis) into a compact
  text block the harness injects into the conversation.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.services import llm_providers as svc


router = APIRouter(prefix="/llm", tags=["llm"])


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

class ProviderUpdateRequest(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = Field(default=None, description="API key to encrypt and store")
    models: Optional[list[str]] = None
    default_model: Optional[str] = None


class TestRequest(BaseModel):
    model: Optional[str] = None


@router.get("/providers")
async def list_llm_providers() -> dict[str, Any]:
    """Catalogue for the Providers page and the harness provider popup."""
    providers = svc.list_providers()
    return {
        "providers": providers,
        "default_provider": svc.default_provider(),
        "groups": [
            {"id": "compatible", "label": "OpenAI-compatible APIs"},
            {"id": "foundation", "label": "Foundation API keys"},
        ],
    }


@router.put("/providers/{provider_id}")
async def update_llm_provider(provider_id: str, request: ProviderUpdateRequest, user: CurrentUser) -> dict[str, Any]:
    """Save base URL / API key / model list for an LLM provider."""
    try:
        svc.save_provider_settings(
            provider_id,
            base_url=request.base_url,
            api_key=request.api_key,
            models=request.models,
            default_model=request.default_model,
        )
    except svc.LlmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # key_store write failure (Supabase unreachable/rejected) — not saved.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"provider": provider_id, "saved": True}


@router.delete("/providers/{provider_id}/key")
async def delete_llm_key(provider_id: str, user: CurrentUser) -> dict[str, Any]:
    try:
        deleted = svc.delete_provider_key(provider_id)
    except svc.LlmError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="No stored key for this provider")
    return {"provider": provider_id, "deleted": True}


@router.get("/providers/{provider_id}/models")
async def get_llm_models(provider_id: str, user: CurrentUser) -> dict[str, Any]:
    """Fetch the model list from the provider's /models endpoint."""
    try:
        models = await svc.fetch_models(provider_id, use_cache=False)
    except svc.LlmError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"provider": provider_id, "models": models}


@router.post("/providers/{provider_id}/test")
async def test_llm_provider(provider_id: str, request: TestRequest, user: CurrentUser) -> dict[str, Any]:
    """Probe the provider with a one-token completion."""
    return await svc.test_provider(provider_id, request.model)


# ---------------------------------------------------------------------------
# Chat harness (SSE)
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    provider: str
    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=8192)


def _sse(event: dict[str, Any]) -> str:
    import json

    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Stream a completion from the chosen provider as Server-Sent Events.

    Events: ``{"type":"delta","text":…}`` repeatedly, then one terminal
    ``{"type":"done","usage":…}`` or ``{"type":"error","message":…}``.
    """

    async def event_stream():
        messages = [message.model_dump() for message in request.messages]
        try:
            async for event in svc.stream_chat(
                request.provider,
                request.model,
                messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                yield _sse(event)
        except svc.LlmError as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Context feeder
# ---------------------------------------------------------------------------

CONTEXT_SECTIONS = ("quote", "candles", "indicators", "news", "calendar", "portfolio", "analysis")

_SECTION_TITLES = {
    "quote": "Live quote",
    "candles": "Recent price history",
    "indicators": "Technical indicators",
    "news": "News headlines",
    "calendar": "Economic calendar",
    "portfolio": "Portfolio positions",
    "analysis": "Gateway pattern analysis",
}


class ContextSection(dict):
    """Plain dict section with a stable shape."""


def _section(section_id: str, status: str, text: str, meta: Optional[dict] = None) -> dict[str, Any]:
    return {
        "id": section_id,
        "title": _SECTION_TITLES[section_id],
        "status": status,
        "text": text.strip(),
        "meta": meta or {},
    }


def _indicators_text(candles: list[dict[str, Any]]) -> str:
    """Compute a compact indicator block from recent closes (stdlib math only)."""
    closes = [float(c["close"]) for c in candles]
    if len(closes) < 15:
        return ""
    lines: list[str] = []

    def sma(period: int) -> float:
        window = closes[-period:]
        return sum(window) / len(window)

    def rsi(period: int = 14) -> float | None:
        if len(closes) < period + 1:
            return None
        gains, losses = 0.0, 0.0
        for prev, curr in zip(closes[-period - 1 : -1], closes[-period:]):
            delta = curr - prev
            if delta >= 0:
                gains += delta
            else:
                losses -= delta
        if losses == 0:
            return 100.0
        rs = gains / losses
        return 100.0 - 100.0 / (1.0 + rs)

    last = closes[-1]
    lines.append(f"Last close: {last:,.2f}")
    lines.append(f"SMA(10): {sma(10):,.2f} · SMA(20): {sma(20):,.2f} · SMA(50): {sma(50):,.2f}" if len(closes) >= 50 else f"SMA(10): {sma(10):,.2f} · SMA(20): {sma(20):,.2f}")
    value = rsi()
    if value is not None:
        lines.append(f"RSI(14): {value:.1f}")
    # MACD(12,26,9) via successive EMA passes.
    if len(closes) >= 26:
        def ema(series: list[float], period: int) -> float:
            k = 2.0 / (period + 1)
            result = series[0]
            for price in series[1:]:
                result = price * k + result * (1 - k)
            return result
        ema12 = ema(closes, 12)
        ema26 = ema(closes, 26)
        macd = ema12 - ema26
        lines.append(f"MACD(12,26,9): {macd:+,.2f} (MACD line)")
    # Realized volatility over the window, annualised roughly by 252 sessions.
    if len(closes) >= 21:
        returns = [(b / a - 1.0) for a, b in zip(closes[-21:-1], closes[-20:])]
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / max(1, len(returns) - 1)
        vol = math.sqrt(variance) * math.sqrt(252) * 100.0
        lines.append(f"Volatility (20-bar, annualised): {vol:.1f}%")
    window = closes[-min(60, len(closes)):]
    lines.append(f"{len(window)}-bar high: {max(window):,.2f} · low: {min(window):,.2f}")
    change = (last / window[0] - 1.0) * 100.0
    lines.append(f"Return over window: {change:+.2f}%")
    return "\n".join(lines)


async def _build_section(section_id: str, symbol: str, tf: str) -> dict[str, Any]:
    """Build one context section, never raising — failures degrade to 'unavailable'."""
    try:
        if section_id == "quote":
            from app.api.main import _fetch_quotes_yfinance_sync
            import asyncio

            rows = await asyncio.to_thread(_fetch_quotes_yfinance_sync, [symbol])
            if not rows:
                return _section("quote", "unavailable", "No live quote available right now.")
            row = rows[0]
            text = (
                f"{row['symbol']}: {row['price']:,.2f} "
                f"({row['change']:+,.2f}, {row['change_pct']:+.2f}%)"
            )
            return _section("quote", "ok", text, {"price": row["price"], "change_pct": row["change_pct"]})

        if section_id == "candles":
            from app.api.main import get_history

            candles = await get_history(ticker=symbol, tf=tf, limit=120, provider="Yahoo Finance")
            if not candles:
                return _section("candles", "unavailable", "No price history available.")
            last_rows = candles[-12:]
            lines = [
                f"{datetime.fromtimestamp(int(c['time']), tz=timezone.utc).strftime('%Y-%m-%d %H:%M')} "
                f"O {c['open']:,.2f} H {c['high']:,.2f} L {c['low']:,.2f} C {c['close']:,.2f}"
                for c in last_rows
            ]
            text = f"Timeframe {tf}; last {len(candles)} bars, most recent {len(last_rows)} shown:\n" + "\n".join(lines)
            return _section("candles", "ok", text, {"bars": len(candles), "tf": tf})

        if section_id == "indicators":
            from app.api.main import get_history

            candles = await get_history(ticker=symbol, tf=tf, limit=120, provider="Yahoo Finance")
            text = _indicators_text(candles)
            if not text:
                return _section("indicators", "unavailable", "Not enough history to compute indicators.")
            return _section("indicators", "ok", text)

        if section_id == "news":
            from app.api.v1.news import get_news

            response = await get_news(symbol=symbol, limit=8, provider="Finnhub")
            if not response.items:
                detail = response.message or "No headlines available."
                return _section("news", "unavailable", detail)
            lines = [
                f"- {item.get('headline') or 'Untitled'}"
                f" ({item.get('source') or 'unknown source'}, {str(item.get('published_at') or '')[:10]})"
                for item in response.items
            ]
            return _section("news", "ok", "\n".join(lines), {"count": len(response.items)})

        if section_id == "calendar":
            from app.api.v1.news import get_calendar

            response = await get_calendar(limit=10, provider="auto")
            if not response.events:
                detail = response.message or "No upcoming events available."
                return _section("calendar", "unavailable", detail)
            lines = [
                f"- {str(e.get('scheduled_at') or '')[:16].replace('T', ' ')} UTC · {e.get('title') or 'event'} · "
                f"{e.get('country', '')} {e.get('currency', '')} · importance "
                f"{str(getattr(e.get('importance'), 'value', e.get('importance')) or 'n/a').lower()} · "
                f"actual {e.get('actual') if e.get('actual') is not None else '—'} / "
                f"forecast {e.get('forecast') if e.get('forecast') is not None else '—'} / "
                f"prior {e.get('prior') if e.get('prior') is not None else '—'}"
                for e in response.events
            ]
            return _section("calendar", "ok", "\n".join(lines), {"count": len(response.events)})

        if section_id == "portfolio":
            from app.api.v1.portfolio import get_portfolio_state

            state = await get_portfolio_state()
            lines = [f"Cash: {state.cash:,.2f} · Equity: {state.equity:,.2f}"]
            for position in state.positions[:15]:
                instrument = position.get("instrument_id") or position.get("symbol") or "?"
                quantity = position.get("quantity", 0)
                market_value = position.get("market_value", 0) or 0
                pnl = position.get("unrealized_pnl", 0) or 0
                lines.append(f"- {instrument}: {quantity:g} units, value {market_value:,.2f}, unrealized P&L {pnl:+,.2f}")
            if len(state.positions) > 15:
                lines.append(f"- … {len(state.positions) - 15} more positions")
            if len(lines) == 1:
                lines.append("- No open positions (flat book)")
            return _section("portfolio", "ok", "\n".join(lines), {"positions": len(state.positions)})

        if section_id == "analysis":
            from app.api.v1.analysis import get_analysis

            result = await get_analysis(symbol)
            signals = result.get("signals") or []
            lines = [
                f"Direction: {result.get('direction')} · confidence {result.get('overall_confidence')}",
                f"RSI: {float(result.get('rsi', 0)):.1f} · price {float(result.get('price', 0)):,.2f}",
            ]
            if signals:
                for signal in signals[:5]:
                    lines.append(f"- Pattern: {signal.get('type')} ({signal.get('direction', 'n/a')})")
            else:
                lines.append("- No chart patterns detected")
            return _section("analysis", "ok", "\n".join(lines), {"patterns": len(signals)})

        return _section(section_id, "unavailable", "Unknown context section.")
    except Exception as exc:  # noqa: BLE001 — one bad source must not break the feeder
        return _section(section_id, "unavailable", f"Section unavailable: {str(exc) or exc.__class__.__name__}")


def assemble_context(symbol: str, sections: list[dict[str, Any]]) -> str:
    """Render the selected sections as one system-prompt-ready text block."""
    header = f"Market context for {symbol.upper()} (generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}):"
    blocks: list[str] = [header]
    for section in sections:
        if section["status"] != "ok" or not section["text"]:
            continue
        blocks.append(f"\n## {section['title']}\n{section['text']}")
    if len(blocks) == 1:
        blocks.append("\n(no context available — answer from the conversation alone)")
    return "\n".join(blocks)


@router.get("/context")
async def get_context(
    symbol: str = "AAPL",
    sections: str = "quote,candles,indicators,news,portfolio",
    tf: str = "1d",
) -> dict[str, Any]:
    """Context feeder: gather selected market data into one text block."""
    wanted = [s.strip().casefold() for s in (sections or "").split(",") if s.strip()]
    unknown = [s for s in wanted if s not in CONTEXT_SECTIONS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown context sections: {', '.join(unknown)}")
    if not wanted:
        wanted = ["quote", "candles", "indicators"]

    symbol = (symbol or "AAPL").strip().upper()
    built: list[dict[str, Any]] = []
    for section_id in CONTEXT_SECTIONS:
        if section_id in wanted:
            built.append(await _build_section(section_id, symbol, tf))
    return {
        "symbol": symbol,
        "tf": tf,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": built,
        "available_sections": list(CONTEXT_SECTIONS),
        "section_titles": dict(_SECTION_TITLES),
        "context": assemble_context(symbol, built),
        "ok_count": sum(1 for s in built if s["status"] == "ok"),
    }
