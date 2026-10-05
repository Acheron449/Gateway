"""Tauric Research TradingAgents integration.

Runs the multi-agent framework (analyst team → bull/bear researchers →
trader → risk management → portfolio manager) inside Gateway jobs:

- The vendored checkout lives at ``backend/vendor/TradingAgents`` (git-ignored)
  and is pip-installed into the environment; availability degrades to a
  clear "not installed" message when it is missing (e.g. inside Docker
  without the install step).
- Gateway's own LLM provider configuration (Providers → AI models) is mapped
  onto TradingAgents' provider registry, so a run uses the same OpenRouter /
  Ollama / Groq / foundation keys the harness chats with.
- Runs are executed on a worker thread with LangChain callback progress
  pushed into the job store; the graph itself is synchronous and blocking.
"""

from __future__ import annotations

import importlib.util
import os
import threading
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.services import job_store
from app.services import llm_providers as llm_svc


VENDOR_DIR = Path(__file__).resolve().parents[2] / "vendor" / "TradingAgents"

ANALYSTS = [
    {"id": "market", "label": "Market / technical", "detail": "Price action, indicators, chart patterns"},
    {"id": "social", "label": "Sentiment", "detail": "StockTwits & Reddit chatter"},
    {"id": "news", "label": "News", "detail": "Headlines and macro events"},
    {"id": "fundamentals", "label": "Fundamentals", "detail": "SEC filings, financials, valuation"},
]

RESEARCH_DEPTHS = [
    {"id": 1, "label": "Light", "detail": "1 debate round — faster, cheaper"},
    {"id": 2, "label": "Standard", "detail": "2 debate rounds — balanced"},
    {"id": 3, "label": "Deep", "detail": "3 debate rounds — most thorough"},
]

# Gateway provider id → (TradingAgents provider, key env var TradingAgents reads).
_PROVIDER_MAP: dict[str, tuple[str, Optional[str]]] = {
    "openai": ("openai", "OPENAI_API_KEY"),
    "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
    "gemini": ("google", "GOOGLE_API_KEY"),
    "openrouter": ("openrouter", "OPENROUTER_API_KEY"),
    "groq": ("groq", "GROQ_API_KEY"),
    "ollama-local": ("ollama", None),
    "ollama-cloud": ("ollama", "OLLAMA_API_KEY"),
    "opencode-zen": ("openai_compatible", "OPENAI_COMPATIBLE_API_KEY"),
    "kilo-gateway": ("openai_compatible", "OPENAI_COMPATIBLE_API_KEY"),
    "cloudflare-ai-gateway": ("openai_compatible", "OPENAI_COMPATIBLE_API_KEY"),
    "custom-openai": ("openai_compatible", "OPENAI_COMPATIBLE_API_KEY"),
}

# Providers whose calls go through TradingAgents' generic OpenAI-compatible
# client (base URL passed via config rather than a provider default endpoint).
_GENERIC_ENDPOINT_PROVIDERS = {"openai_compatible", "ollama"}

_RUN_LOCK = threading.Lock()

_NODE_LABELS = {
    "market_analyst": "Market analyst writing its report",
    "sentiment_analyst": "Sentiment analyst reading social chatter",
    "news_analyst": "News analyst scanning headlines",
    "fundamentals_analyst": "Fundamentals analyst reviewing filings",
    "social_analyst": "Sentiment analyst reading social chatter",
    "bull_researcher": "Bull researcher arguing the case",
    "bear_researcher": "Bear researcher arguing the case",
    "research_manager": "Research manager weighing the debate",
    "trader": "Trader drafting the proposal",
    "aggressive_analyst": "Risk team debating (aggressive view)",
    "conservative_analyst": "Risk team debating (conservative view)",
    "neutral_analyst": "Risk team debating (neutral view)",
    "risk_manager": "Risk management reviewing the proposal",
    "portfolio_manager": "Portfolio manager making the final call",
}

_SECTION_KEYS = [
    ("market_report", "Market analyst report"),
    ("sentiment_report", "Sentiment analyst report"),
    ("news_report", "News analyst report"),
    ("fundamentals_report", "Fundamentals analyst report"),
    ("investment_plan", "Research manager conclusion"),
    ("trader_investment_plan", "Trader proposal"),
    ("final_trade_decision", "Portfolio manager decision"),
]


# ---------------------------------------------------------------------------
# Availability & configuration
# ---------------------------------------------------------------------------

def tradingagents_available() -> dict[str, Any]:
    spec = importlib.util.find_spec("tradingagents")
    available = spec is not None
    version = None
    if available:
        try:
            import tradingagents

            version = getattr(tradingagents, "__version__", None)
        except Exception:  # noqa: BLE001 - treat any import failure as missing
            available = False
    return {
        "available": available,
        "version": version,
        "vendored": VENDOR_DIR.exists(),
        "message": None
        if available
        else "TradingAgents is not installed in this environment — run `pip install vendor/TradingAgents` on the Gateway server.",
    }


def supported_providers() -> list[dict[str, Any]]:
    """LLM providers that map onto TradingAgents' provider registry."""
    rows = []
    for provider in llm_svc.list_providers():
        mapping = _PROVIDER_MAP.get(provider["id"])
        if mapping is None:
            continue
        rows.append({
            **{k: provider[k] for k in ("id", "label", "group", "detail", "configured", "has_key", "default_model")},
            "tradingagents_provider": mapping[0],
        })
    return rows


def _resolve(provider_id: str) -> tuple[str, Optional[str], Optional[str], Optional[str]]:
    """→ (tradingagents provider, backend_url, api_key, key env name)."""
    mapping = _PROVIDER_MAP.get((provider_id or "").strip().casefold())
    if mapping is None:
        raise llm_svc.LlmError(
            f"Provider '{provider_id}' cannot drive TradingAgents — choose one from the provider list"
        )
    ta_provider, key_env = mapping
    base_url, api_key = llm_svc.resolve_endpoint(provider_id)
    backend_url = base_url if ta_provider in _GENERIC_ENDPOINT_PROVIDERS else None
    return ta_provider, backend_url, api_key, key_env


def _data_dir() -> Path:
    root = os.getenv("GATEWAY_DATA_DIR", "").strip()
    base = Path(root) if root else Path.home() / ".gateway"
    return base / "tradingagents"


def _build_config(
    *,
    ta_provider: str,
    backend_url: Optional[str],
    model: str,
    depth: int,
    language: str,
) -> dict[str, Any]:
    from tradingagents.default_config import build_default_config

    config = build_default_config()
    config["llm_provider"] = ta_provider
    config["deep_think_llm"] = model
    config["quick_think_llm"] = model
    config["backend_url"] = backend_url
    config["max_debate_rounds"] = depth
    config["max_risk_discuss_rounds"] = depth
    config["output_language"] = language or "English"
    data_dir = _data_dir()
    config["results_dir"] = str(data_dir / "results")
    config["data_cache_dir"] = str(data_dir / "cache")
    config["memory_log_path"] = str(data_dir / "memory" / "trading_memory.md")
    config["checkpoint_enabled"] = False
    for key in ("results_dir", "data_cache_dir"):
        Path(config[key]).mkdir(parents=True, exist_ok=True)
    Path(config["memory_log_path"]).parent.mkdir(parents=True, exist_ok=True)
    return config


def _make_progress_handler(job_id: Optional[str]):
    """LangChain callback that streams stage/call-count progress into a job."""
    if not job_id:
        return None
    try:
        from langchain_core.callbacks import BaseCallbackHandler
    except Exception:  # noqa: BLE001 - progress is best-effort
        return None

    class _Handler(BaseCallbackHandler):  # type: ignore[misc, valid-type]
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def _bump(self, stage: str | None = None) -> None:
            self.calls += 1
            progress = min(0.9, 0.15 + self.calls * 0.04)
            message = stage or f"Model call #{self.calls}"
            job_store.update(job_id, progress=round(progress, 3), message=message)

        def on_chat_model_start(self, serialized, messages, **kwargs):
            metadata = kwargs.get("metadata") or {}
            node = str(metadata.get("langgraph_node") or "")
            self._bump(_NODE_LABELS.get(node))

        def on_llm_start(self, serialized, prompts, **kwargs):
            self._bump()

        def on_tool_start(self, serialized, input_str, **kwargs):
            metadata = kwargs.get("metadata") or {}
            node = str(metadata.get("langgraph_node") or "")
            if node in _NODE_LABELS:
                self._bump(_NODE_LABELS[node])

    return _Handler()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def _normalize_date(value: Optional[str]) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise llm_svc.LlmError("Analysis date must be formatted YYYY-MM-DD") from exc
    if parsed.date() > date_cls.today():
        raise llm_svc.LlmError("Analysis date cannot be in the future")
    return parsed.strftime("%Y-%m-%d")


def _extract_sections(final_state: Any) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    if not isinstance(final_state, dict):
        return sections
    for key, label in _SECTION_KEYS:
        value = final_state.get(key)
        if isinstance(value, str) and value.strip():
            sections.append({"id": key, "label": label, "text": value.strip()[:6000]})
    # Debate histories add useful colour without dumping full transcripts.
    for state_key, label in (
        ("investment_debate_state", "Bull vs bear debate"),
        ("risk_debate_state", "Risk team debate"),
    ):
        state = final_state.get(state_key)
        if isinstance(state, dict):
            history = state.get("history")
            if isinstance(history, str) and history.strip():
                sections.append({"id": state_key, "label": label, "text": history.strip()[-4000:]})
    return sections


def run_trading_agents(
    *,
    ticker: str,
    analysis_date: Optional[str],
    analysts: list[str],
    provider_id: str,
    model: Optional[str],
    depth: int,
    language: str,
    job_id: Optional[str] = None,
) -> dict[str, Any]:
    """Blocking multi-agent run (call from a worker thread)."""
    availability = tradingagents_available()
    if not availability["available"]:
        raise RuntimeError(availability["message"])

    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError(
            "Another TradingAgents analysis is already running — wait for it to finish"
        )
    try:
        trade_date = _normalize_date(analysis_date)
        selected = [a for a in analysts if a in {row["id"] for row in ANALYSTS}] or ["market"]
        ta_provider, backend_url, api_key, key_env = _resolve(provider_id)
        resolved_model = (model or llm_svc.stored_settings(provider_id).get("default_model") or "").strip()
        if not resolved_model:
            raise llm_svc.LlmError(
                f"No model chosen for {provider_id} — pick a model in the harness or Providers page first"
            )
        depth = max(1, min(int(depth or 1), 3))

        # TradingAgents reads provider keys from the environment at client
        # construction; scoped mutation guarded by _RUN_LOCK.
        if api_key and key_env:
            os.environ[key_env] = api_key
        if ta_provider == "ollama" and api_key:
            os.environ.setdefault("OLLAMA_API_KEY", api_key)

        config = _build_config(
            ta_provider=ta_provider,
            backend_url=backend_url,
            model=resolved_model,
            depth=depth,
            language=language,
        )
        handler = _make_progress_handler(job_id)
        if job_id:
            job_store.update(
                job_id,
                progress=0.12,
                message=f"Launching {len(selected)} analyst(s) on {ticker.upper()} @ {trade_date}…",
            )

        from tradingagents.graph.trading_graph import TradingAgentsGraph

        graph = TradingAgentsGraph(
            selected_analysts=tuple(selected),
            debug=False,
            config=config,
            callbacks=[handler] if handler else None,
        )
        final_state, signal = graph.propagate(ticker.upper(), trade_date)

        if job_id:
            job_store.update(job_id, progress=0.95, message="Collecting reports…")
        sections = _extract_sections(final_state)
        return {
            "ticker": ticker.upper(),
            "date": trade_date,
            "signal": signal,
            "rating": (final_state.get("final_rating") if isinstance(final_state, dict) else None) or signal,
            "analysts": selected,
            "provider": provider_id,
            "tradingagents_provider": ta_provider,
            "model": resolved_model,
            "depth": depth,
            "sections": sections,
            "llm_calls": getattr(handler, "calls", 0) if handler else None,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "Research output from TradingAgents — not financial advice.",
        }
    finally:
        _RUN_LOCK.release()


def start_trading_agents_job(
    *,
    ticker: str,
    analysis_date: Optional[str],
    analysts: list[str],
    provider_id: str,
    model: Optional[str],
    depth: int,
    language: str,
) -> str:
    """Create a job and run the analysis on a worker thread."""
    job_id = job_store.create(
        "trading-agents",
        {
            "ticker": ticker.upper(),
            "date": analysis_date,
            "analysts": analysts,
            "provider": provider_id,
            "model": model,
            "depth": depth,
        },
    )

    def worker(active_id: str) -> None:
        result = run_trading_agents(
            ticker=ticker,
            analysis_date=analysis_date,
            analysts=analysts,
            provider_id=provider_id,
            model=model,
            depth=depth,
            language=language,
            job_id=active_id,
        )
        job_store.update(active_id, result=result, progress=1.0, message=f"Decision: {result['signal']}")

    job_store.run_worker(job_id, worker)
    return job_id
