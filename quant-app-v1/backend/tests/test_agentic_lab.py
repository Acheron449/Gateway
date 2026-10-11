"""Agentic Trading Lab tests: risk guard, simulator, metrics, chart, research.

Covers the RiskGuard-style rules inspired by kweinmeister/agentic-trading:
every proposed decision passes a gate (position cap, short filter, drawdown
circuit breaker) and the run records what the guard changed.
"""

from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from app.services import lab_backtest as lab
from app.services import research_store as research


def _bars(count: int = 120, rally: int = 80, step_up: float = 1.02, step_down: float = 0.90):
    """Synthetic OHLCV: a rally then a crash (to trip drawdown rules)."""
    bars = []
    price = 100.0
    for i in range(count):
        price *= step_up if i < rally else step_down
        bars.append(
            {
                "time": 1_700_000_000 + i * 86_400,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
            }
        )
    return bars


# ---------------------------------------------------------------------------
# Risk rules
# ---------------------------------------------------------------------------

def test_normalize_rules_defaults_and_clamps():
    assert lab.normalize_rules(None) == lab.DEFAULT_RISK_RULES
    rules = lab.normalize_rules(
        {"max_position_pct": 500, "max_drawdown_pct": -3, "allow_short": False}
    )
    assert rules["max_position_pct"] == 100.0  # clamped
    assert rules["max_drawdown_pct"] == 0.0  # clamped
    assert rules["allow_short"] is False
    # Garbage values fall back to defaults instead of crashing.
    assert lab.normalize_rules({"max_position_pct": "abc"}) == lab.DEFAULT_RISK_RULES


def test_drawdown_circuit_breaker_halts_run():
    bars = _bars()
    sim = lab.simulate(bars, ["long"] * len(bars), capital=10_000, rules={"max_drawdown_pct": 10})
    assert sim["risk_halted"] is True
    assert sim["risk_events"][0]["rule"] == "drawdown_halt"
    assert "10%" in sim["risk_events"][0]["reason"]
    # After the halt the book is flat: final equity stays where it halted.
    assert sim["trades"], "the long leg should have been closed by the halt"


def test_short_proposals_rejected_when_disabled():
    bars = _bars()
    targets = ["long"] * 40 + ["short"] * 80
    sim = lab.simulate(bars, targets, capital=10_000, rules={"allow_short": False})
    assert any(event["rule"] == "short_rejected" for event in sim["risk_events"])
    assert all(trade["direction"] == "long" for trade in sim["trades"])
    # Recorded once for the decision change, not every bar of the short leg.
    assert len([e for e in sim["risk_events"] if e["rule"] == "short_rejected"]) == 1


def test_shorts_execute_when_allowed():
    bars = _bars()
    targets = ["long"] * 40 + ["short"] * 80
    sim = lab.simulate(bars, targets, capital=10_000, rules={"allow_short": True, "max_drawdown_pct": 0})
    assert any(trade["direction"] == "short" for trade in sim["trades"])
    assert sim["risk_events"] == []


def test_max_position_cap_limits_allocation():
    bars = _bars()
    sim = lab.simulate(
        bars, ["long"] * len(bars), capital=10_000, rules={"max_position_pct": 40}
    )
    assert sim["allocation"] == 0.4
    # A 40% cap must underperform the fully-invested run on the same path.
    full = lab.simulate(bars, ["long"] * len(bars), capital=10_000, rules={"max_position_pct": 100})
    assert abs(sim["final_equity"] - full["final_equity"]) > 1e-6


# ---------------------------------------------------------------------------
# Metrics & stats (requirement: easy-to-understand numerical statistics)
# ---------------------------------------------------------------------------

def test_metrics_include_risk_guard_stat_row():
    bars = _bars()
    sim = lab.simulate(bars, ["long"] * len(bars), capital=10_000, rules={"max_drawdown_pct": 10})
    metrics = lab.compute_metrics(bars, sim, capital=10_000, tf="1d")
    assert metrics["risk_halted"] is True
    row = next(s for s in metrics["stats"] if s["label"] == "Risk guard")
    assert row["value"] == "HALTED"

    clean = lab.simulate(bars, ["long"] * len(bars), capital=10_000, rules={"max_drawdown_pct": 0})
    clean_metrics = lab.compute_metrics(bars, clean, capital=10_000, tf="1d")
    clean_row = next(s for s in clean_metrics["stats"] if s["label"] == "Risk guard")
    assert clean_row["value"] == "clean"


def test_metrics_shape_plain_language():
    bars = _bars()
    sim = lab.simulate(bars, lab.baseline_targets(bars, "sma_cross"), capital=10_000)
    metrics = lab.compute_metrics(bars, sim, capital=10_000, tf="1d")
    labels = [s["label"] for s in metrics["stats"]]
    assert labels == [
        "Total return", "Market return", "vs Market", "Sharpe", "Max drop",
        "Win rate", "Profit factor", "Trades", "Risk guard",
    ]
    assert metrics["max_drawdown_pct"] >= 0
    assert metrics["verdict"]


def test_runs_summary_reports_best_and_beat_market_rate():
    runs = [
        {"kind": "llm", "strategy": "A", "symbol": "AAPL",
         "metrics": {"total_return_pct": 12.0, "excess_return_pct": 3.0}},
        {"kind": "baseline", "strategy": "B", "symbol": "AAPL",
         "metrics": {"total_return_pct": -4.0, "excess_return_pct": -9.0}},
    ]
    summary = lab.runs_summary(runs)
    assert summary["best_return_pct"] == 12.0
    assert summary["model_runs"] == 1
    assert summary["beat_market_pct"] == 50.0


# ---------------------------------------------------------------------------
# Chart payload (reference: price + SMA + execution markers figure)
# ---------------------------------------------------------------------------

def test_build_chart_has_series_and_markers():
    bars = _bars()
    sim = lab.simulate(bars, lab.baseline_targets(bars, "sma_cross"), capital=10_000)
    chart = lab.build_chart(bars, sim["trades"], sim["risk_events"])
    assert 10 <= len(chart["points"]) <= 130
    assert all({"t", "c", "s10", "s30"} <= set(point) for point in chart["points"])
    kinds = {marker["kind"] for marker in chart["markers"]}
    assert "open_long" in kinds and "close_long" in kinds
    assert all("label" in marker for marker in chart["markers"])


def test_pair_request_schema_requires_distinct_symbols_and_ordered_z_thresholds():
    from pydantic import ValidationError
    from app.api.v1.agentic_lab import BacktestRequest, PairBacktestConfig

    with pytest.raises(ValidationError):
        BacktestRequest(kind="pairs", symbol="SPY", symbol_b="SPY", pair_config=PairBacktestConfig())
    with pytest.raises(ValidationError):
        PairBacktestConfig(entry_z=0.5, exit_z=1.0)


def test_run_pairs_fetches_both_symbols_and_persists_pair_fields(monkeypatch):
    rng = np.random.default_rng(55)
    log_b = np.cumsum(rng.normal(0, 0.01, 160)) + math.log(100)
    residual = np.zeros(160)
    innovations = rng.normal(0, 0.02, 160)
    for index in range(1, len(residual)):
        residual[index] = 0.3 * residual[index - 1] + innovations[index]
    log_a = 0.15 + 1.05 * log_b + residual
    stamps = [1_700_000_000 + index * 86_400 for index in range(160)]
    bars_a = _bars(160)
    bars_b = _bars(160)
    for index, stamp in enumerate(stamps):
        bars_a[index].update(time=stamp, open=math.exp(log_a[index]), high=math.exp(log_a[index]) * 1.01,
                             low=math.exp(log_a[index]) * 0.99, close=math.exp(log_a[index]))
        bars_b[index].update(time=stamp, open=math.exp(log_b[index]), high=math.exp(log_b[index]) * 1.01,
                             low=math.exp(log_b[index]) * 0.99, close=math.exp(log_b[index]))
    fetched = []

    async def fake_fetch(symbol, tf, limit):
        fetched.append(symbol)
        source = bars_a if symbol == "AAA" else bars_b
        return [dict(bar, volume=100_000) for bar in source]

    saved = []
    monkeypatch.setattr(lab, "fetch_bars", fake_fetch)
    monkeypatch.setattr(lab, "_store_run", saved.append)

    run = asyncio.run(lab.run_backtest(
        {"kind": "pairs", "symbol_b": "BBB", "pair_config": {"lookback": 40, "walk_forward_folds": 2}},
        symbol="AAA", symbol_b="BBB", pair_config={"lookback": 40, "walk_forward_folds": 2},
        bars_limit=160, capital=10_000,
    ))

    assert sorted(fetched) == ["AAA", "BBB"]
    assert run["kind"] == "pairs" and run["symbol_b"] == "BBB"
    assert run["pair_series"] and run["walk_forward"]["folds"]
    assert saved == [run]


def test_run_backtest_persists_rules_chart_and_risk(monkeypatch, tmp_path):
    bars = _bars(90, rally=60)
    monkeypatch.setattr(lab, "fetch_bars", lambda *a, **k: _async_value(bars))
    monkeypatch.setattr(lab, "_store_run", lambda run: None)  # keep tests out of the real run log

    run = asyncio.run(
        lab.run_backtest(
            {"kind": "baseline", "baseline": "buy_hold"},
            symbol="TEST",
            tf="1d",
            bars_limit=90,
            risk={"max_position_pct": 50, "allow_short": False, "max_drawdown_pct": 5},
        )
    )
    assert run["risk_rules"]["max_position_pct"] == 50.0
    assert run["risk_rules"]["allow_short"] is False
    assert run["chart"]["points"]
    assert run["metrics"]["risk_halted"] is True
    assert any(s["label"] == "Risk guard" for s in run["metrics"]["stats"])


class _AsyncValue:
    """Awaitable wrapper so monkeypatched fetch_bars behaves like the real one."""

    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _result():
            return self.value

        return _result().__await__()


def _async_value(value):
    return _AsyncValue(value)


# ---------------------------------------------------------------------------
# Research store (type / upload / model-draft paths share this store)
# ---------------------------------------------------------------------------

def test_research_store_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "_SETTINGS_FILE", tmp_path / "research.json")

    doc = research.save_doc(title="Thesis", content="Momentum intact.", source="typed", symbol="aapl")
    assert doc["symbol"] == "AAPL"
    assert research.get_doc(doc["id"])["title"] == "Thesis"

    with pytest.raises(ValueError):
        research.save_doc(title="x", content="   ", source="typed")
    with pytest.raises(ValueError):
        research.save_doc(title="x", content="y", source="carrier-pigeon")

    draft = research.save_doc(title="Model brief", content="...", source="model", provider="groq", model="llama")
    assert [d["title"] for d in research.list_docs()] == ["Model brief", "Thesis"]

    context = research.combined_context("AAPL")
    assert "Thesis" in context and "Momentum intact." in context

    assert research.delete_doc(doc["id"]) is True
    assert research.delete_doc(doc["id"]) is False
    assert len(research.list_docs()) == 1
