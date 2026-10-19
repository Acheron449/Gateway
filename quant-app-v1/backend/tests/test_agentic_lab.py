"""Agentic Trading Lab tests: risk guard, simulator, metrics, chart, research."""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import datetime, timezone

import httpx
import numpy as np
import pytest

from app.api.main import app
from app.auth import User, create_access_token
from fastapi import HTTPException
from app.api.v1 import agentic_lab as lab_api
from app.services import job_store
from app.services import lab_backtest as lab
from app.services import research_store as research


def test_tradingagents_routes_are_removed_without_removing_shared_lab_or_llm():
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert not {"/agents/trading-agents", "/agents/trading-agents/run", "/agents/jobs", "/agents/jobs/{job_id}"} & paths
    assert "/agentic-lab/backtest" in paths and "/llm/providers" in paths
    assert "/agentic-lab/monte-carlo" in paths and "/agentic-lab/research-jobs" in paths


def _bars(count: int = 120, rally: int = 80, step_up: float = 1.02, step_down: float = 0.90):
    bars = []
    price = 100.0
    for index in range(count):
        price *= step_up if index < rally else step_down
        bars.append({"time": 1_700_000_000 + index * 86_400, "open": price, "high": price, "low": price, "close": price})
    return bars


class _AsyncValue:
    def __init__(self, value): self.value = value
    def __await__(self):
        async def result(): return self.value
        return result().__await__()


def _async_value(value): return _AsyncValue(value)


def test_normalize_rules_defaults_and_clamps():
    assert lab.normalize_rules(None) == lab.DEFAULT_RISK_RULES
    rules = lab.normalize_rules({"max_position_pct": 500, "max_drawdown_pct": -3, "allow_short": False})
    assert rules["max_position_pct"] == 100.0 and rules["max_drawdown_pct"] == 0.0 and rules["allow_short"] is False
    assert lab.normalize_rules({"max_position_pct": "abc"}) == lab.DEFAULT_RISK_RULES


def test_drawdown_circuit_breaker_halts_run():
    sim = lab.simulate(_bars(), ["long"] * 120, capital=10_000, rules={"max_drawdown_pct": 10})
    assert sim["risk_halted"] and sim["risk_events"][0]["rule"] == "drawdown_halt"
    assert "10%" in sim["risk_events"][0]["reason"] and sim["trades"]


def test_short_proposals_rejected_when_disabled():
    sim = lab.simulate(_bars(), ["long"] * 40 + ["short"] * 80, capital=10_000, rules={"allow_short": False})
    assert any(event["rule"] == "short_rejected" for event in sim["risk_events"])
    assert all(trade["direction"] == "long" for trade in sim["trades"])
    assert len([event for event in sim["risk_events"] if event["rule"] == "short_rejected"]) == 1


def test_shorts_execute_when_allowed():
    sim = lab.simulate(_bars(), ["long"] * 40 + ["short"] * 80, capital=10_000, rules={"allow_short": True, "max_drawdown_pct": 0})
    assert any(trade["direction"] == "short" for trade in sim["trades"]) and sim["risk_events"] == []


def test_max_position_cap_limits_allocation():
    bars = _bars()
    sim = lab.simulate(bars, ["long"] * len(bars), capital=10_000, rules={"max_position_pct": 40})
    full = lab.simulate(bars, ["long"] * len(bars), capital=10_000, rules={"max_position_pct": 100})
    assert sim["allocation"] == 0.4 and abs(sim["final_equity"] - full["final_equity"]) > 1e-6


def test_metrics_include_risk_guard_stat_row():
    bars = _bars(); sim = lab.simulate(bars, ["long"] * len(bars), capital=10_000, rules={"max_drawdown_pct": 10})
    metrics = lab.compute_metrics(bars, sim, capital=10_000, tf="1d")
    assert metrics["risk_halted"] and next(row for row in metrics["stats"] if row["label"] == "Risk guard")["value"] == "HALTED"


def test_metrics_shape_plain_language():
    bars = _bars(); sim = lab.simulate(bars, lab.baseline_targets(bars, "sma_cross"), capital=10_000)
    metrics = lab.compute_metrics(bars, sim, capital=10_000, tf="1d")
    assert [row["label"] for row in metrics["stats"]] == ["Total return", "Market return", "vs Market", "Sharpe", "Max drop", "Win rate", "Profit factor", "Trades", "Risk guard"]
    assert metrics["max_drawdown_pct"] >= 0 and metrics["verdict"]


def test_runs_summary_reports_best_and_beat_market_rate():
    summary = lab.runs_summary([{"kind": "llm", "metrics": {"total_return_pct": 12, "excess_return_pct": 3}}, {"kind": "baseline", "metrics": {"total_return_pct": -4, "excess_return_pct": -9}}])
    assert summary["best_return_pct"] == 12 and summary["model_runs"] == 1 and summary["beat_market_pct"] == 50


def test_build_chart_has_series_and_markers():
    bars = _bars(); sim = lab.simulate(bars, lab.baseline_targets(bars, "buy_hold"), capital=10_000)
    chart = lab.build_chart(bars, sim["trades"], sim["risk_events"])
    assert 10 <= len(chart["points"]) <= 130 and all({"t", "c", "s10", "s30"} <= set(point) for point in chart["points"])
    assert {marker["kind"] for marker in chart["markers"]} >= {"open_long", "close_long"}


def test_pair_request_schema_requires_distinct_symbols_and_ordered_z_thresholds():
    from pydantic import ValidationError
    from app.api.v1.agentic_lab import BacktestRequest, PairBacktestConfig
    with pytest.raises(ValidationError): BacktestRequest(kind="pairs", symbol="SPY", symbol_b="SPY", pair_config=PairBacktestConfig())
    with pytest.raises(ValidationError): PairBacktestConfig(entry_z=0.5, exit_z=1.0)


def test_run_backtest_persists_rules_chart_and_risk(monkeypatch):
    bars = _bars(90, rally=60)
    monkeypatch.setattr(lab, "fetch_bars", lambda *a, **k: _async_value(bars))
    monkeypatch.setattr(lab, "_store_run", lambda run: None)
    run = asyncio.run(lab.run_backtest({"kind": "baseline", "baseline": "buy_hold"}, symbol="TEST", bars_limit=90, risk={"max_position_pct": 50, "allow_short": False, "max_drawdown_pct": 5}))
    assert run["risk_rules"]["max_position_pct"] == 50 and run["risk_rules"]["allow_short"] is False
    assert run["chart"]["points"] and run["metrics"]["risk_halted"]


def _mc_run(run_id: str, returns: list[float], **extra):
    return {"id": run_id, "kind": "baseline", "strategy": run_id, "symbol": "TEST", "bar_returns": returns, **extra}


def test_bootstrap_monte_carlo_is_seeded_bounded_and_distinct():
    runs = [_mc_run("run-a", [0.01, -0.02, 0.015]), _mc_run("run-b", [-0.01, 0.02, 0.005])]
    kwargs = dict(simulations=100, horizon=25, confidence=0.9, seed=42, start_capital=5000)
    first = lab.bootstrap_monte_carlo(runs, **kwargs)
    assert first == lab.bootstrap_monte_carlo(runs, **kwargs) and len(first["series"]) == 2
    for series in first["series"]:
        assert series["points"][0] == {"step": 0, "median": 5000, "lower": 5000, "upper": 5000}
        assert len(series["points"]) <= 120 and all(p["lower"] <= p["median"] <= p["upper"] for p in series["points"])
    changed = lab.bootstrap_monte_carlo([_mc_run("run-a", [0.2, -0.2])], **kwargs)
    assert changed["series"][0]["points"] != first["series"][0]["points"]


@pytest.mark.parametrize("override", [{"simulations": 99}, {"horizon": 19}, {"confidence": 1.0}, {"seed": -1}, {"start_capital": 0}])
def test_bootstrap_monte_carlo_rejects_invalid_caps(override):
    kwargs = dict(simulations=100, horizon=20, confidence=0.9, seed=1, start_capital=1000); kwargs.update(override)
    with pytest.raises(ValueError): lab.bootstrap_monte_carlo([_mc_run("run", [0.01])], **kwargs)


def test_bootstrap_monte_carlo_rejects_aggregate_work_over_limit():
    runs = [_mc_run(f"run-{index}", [0.01]) for index in range(5)]
    with pytest.raises(ValueError, match="4,000,000-point limit"):
        lab.bootstrap_monte_carlo(runs, simulations=1000, horizon=1000, confidence=0.9, seed=1, start_capital=1000)


def test_bootstrap_monte_carlo_rejects_flat_and_invalid_equity_histories():
    # A zero-return series is not informative enough to claim a meaningful resampling comparison.
    with pytest.raises(ValueError, match="non-zero"):
        lab.bootstrap_monte_carlo([_mc_run("flat", [0.0] * 20)], simulations=100, horizon=20, confidence=0.9, seed=1, start_capital=1000)
    with pytest.raises(ValueError, match="non-finite"):
        lab.bootstrap_monte_carlo([_mc_run("overflow", [1e308])], simulations=100, horizon=20, confidence=0.9, seed=1, start_capital=1000)


@pytest.mark.parametrize("run", [{"id": "legacy", "kind": "baseline"}, _mc_run("bad", [-1]), _mc_run("nan", [float("nan")]), _mc_run("pair", [0.01], kind="pairs", symbol_b="XYZ")])
def test_bootstrap_monte_carlo_rejects_unsupported_histories(run):
    with pytest.raises(ValueError): lab.bootstrap_monte_carlo([run], simulations=100, horizon=20, confidence=0.9, seed=1, start_capital=1000)


def test_run_backtest_persists_full_resolution_bar_returns(monkeypatch):
    bars = _bars(90, rally=60); saved = []
    monkeypatch.setattr(lab, "fetch_bars", lambda *a, **k: _async_value(bars)); monkeypatch.setattr(lab, "_store_run", saved.append)
    run = asyncio.run(lab.run_backtest({"kind": "baseline", "baseline": "buy_hold"}, symbol="TEST", bars_limit=90, owner_user_id="owner-a", research_job_id="job-a", research_iteration=1))
    assert len(run["equity_curve"]) <= 60 and len(run["bar_returns"]) == len(bars) - 1 and saved[0]["bar_returns"] == run["bar_returns"]
    assert run["owner_user_id"] == "owner-a" and run["research_job_id"] == "job-a" and run["research_iteration"] == 1


def test_visible_runs_and_delete_are_owner_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "_SETTINGS_FILE", tmp_path / "runs.json")
    lab._store_run({"id": "shared"}); lab._store_run({"id": "a", "owner_user_id": "user-a"}); lab._store_run({"id": "b", "owner_user_id": "user-b"})
    assert {r["id"] for r in lab.visible_runs(None)} == {"shared"} and {r["id"] for r in lab.visible_runs("user-a")} == {"shared", "a"}
    assert not lab.delete_run("b", owner_user_id="user-a") and lab.delete_run("a", owner_user_id="user-a")
    assert lab.delete_run("shared", owner_user_id="user-a")


def test_research_store_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "_SETTINGS_FILE", tmp_path / "research.json")
    doc = research.save_doc(title="Thesis", content="Momentum intact.", source="typed", symbol="aapl")
    assert doc["symbol"] == "AAPL" and research.get_doc(doc["id"])["title"] == "Thesis"
    with pytest.raises(ValueError): research.save_doc(title="x", content="   ", source="typed")
    with pytest.raises(ValueError): research.save_doc(title="x", content="y", source="carrier-pigeon")
    research.save_doc(title="Model brief", content="...", source="model", provider="groq", model="llama")
    assert [d["title"] for d in research.list_docs()] == ["Model brief", "Thesis"]
    assert "Thesis" in research.combined_context("AAPL") and research.delete_doc(doc["id"])
    assert not research.delete_doc(doc["id"]) and len(research.list_docs()) == 1


def test_research_store_owner_filters_and_private_delete(monkeypatch, tmp_path):
    monkeypatch.setattr(research, "_SETTINGS_FILE", tmp_path / "research.json")
    shared = research.save_doc(title="Shared", content="Legacy", source="typed")
    private = research.save_doc(title="Private", content="Owner-only thesis", source="model", owner_user_id="user-a", research_job_id="job-a", research_iteration=2)
    assert [doc["id"] for doc in research.list_docs()] == [shared["id"]]
    assert {doc["id"] for doc in research.list_docs("user-a")} == {shared["id"], private["id"]}
    assert "Owner-only thesis" not in research.combined_context() and "Owner-only thesis" in research.owner_context("user-a", research_job_id="job-a")
    assert "Owner-only thesis" not in research.owner_context("user-b", research_job_id="job-a")
    assert not research.delete_doc(private["id"], owner_user_id="user-b") and research.delete_doc(private["id"], owner_user_id="user-a")


@pytest.mark.asyncio
async def test_private_collection_filters_and_monte_carlo_api(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "_SETTINGS_FILE", tmp_path / "runs.json")
    monkeypatch.setattr(research, "_SETTINGS_FILE", tmp_path / "research.json")
    lab._store_run({"id": "shared", "kind": "baseline", "bar_returns": [0.01] * 20, "metrics": {}, "decisions": []})
    lab._store_run({"id": "private", "owner_user_id": "alice", "kind": "baseline", "bar_returns": [0.02] * 20, "metrics": {}, "decisions": []})
    research.save_doc(title="Shared", content="shared", source="typed")
    research.save_doc(title="Alice only", content="private", source="model", owner_user_id="alice")
    timestamp = datetime.now(timezone.utc).timestamp()
    lab._store_run({"id": "alice-log", "owner_user_id": "alice", "kind": "llm", "symbol": "TEST", "strategy": "Alice strategy", "created_at": datetime.now(timezone.utc).isoformat(), "decisions": [{"time": timestamp, "action": "long", "price": 100, "reason": "private log"}]})
    lab._store_run({"id": "bob-log", "owner_user_id": "bob", "kind": "llm", "symbol": "TEST", "strategy": "Bob strategy", "created_at": datetime.now(timezone.utc).isoformat(), "decisions": [{"time": timestamp, "action": "short", "price": 100, "reason": "other private log"}]})
    alice_runs = await lab_api.get_runs(user=User(id="alice", email="a@example.test"))
    bob_runs = await lab_api.get_runs(user=User(id="bob", email="b@example.test"))
    assert {run["id"] for run in alice_runs["runs"]} == {"shared", "private", "alice-log"}
    assert {run["id"] for run in bob_runs["runs"]} == {"shared", "bob-log"}
    assert all("owner_user_id" not in run for run in alice_runs["runs"])
    alice_log = await lab_api.get_trading_log(user=User(id="alice", email="a@example.test"))
    bob_log = await lab_api.get_trading_log(user=User(id="bob", email="b@example.test"))
    assert {entry["run_id"] for entry in alice_log["entries"]} == {"alice-log"}
    assert {entry["run_id"] for entry in bob_log["entries"]} == {"bob-log"}
    alice_docs = await lab_api.get_research(user=User(id="alice", email="a@example.test"))
    bob_docs = await lab_api.get_research(user=User(id="bob", email="b@example.test"))
    assert len(alice_docs["research"]) == 2 and len(bob_docs["research"]) == 1
    with pytest.raises(Exception): await lab_api.monte_carlo(lab_api.MonteCarloRequest(run_ids=["private"], simulations=100, horizon=20), User(id="bob", email="b@example.test"))
    result = await lab_api.monte_carlo(lab_api.MonteCarloRequest(run_ids=["private"], simulations=100, horizon=20), User(id="alice", email="a@example.test"))
    assert result["series"][0]["run_id"] == "private"


@pytest.mark.asyncio
async def test_backtest_job_polling_is_authenticated_and_owner_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "_SETTINGS_FILE", tmp_path / "runs.json")
    monkeypatch.setattr(lab, "fetch_bars", lambda *a, **k: _async_value(_bars(50)))
    job_store._JOBS.clear()
    job_store._CANCEL_EVENTS.clear()
    owner = User(id="job-owner", email="owner@example.test")
    other = User(id="job-other", email="other@example.test")

    created = await lab_api.start_backtest(lab_api.BacktestRequest(kind="baseline", baseline="buy_hold", symbol="TEST"), owner)
    job_id = created["job_id"]
    for _ in range(200):
        job = job_store.get(job_id)
        if job and job["status"] in job_store.TERMINAL_STATUSES:
            break
        await asyncio.sleep(0.01)
    assert job_store.get(job_id)["meta"]["owner_user_id"] == owner.id
    assert (await lab_api.get_job(job_id, owner))["id"] == job_id
    with pytest.raises(HTTPException) as error:
        await lab_api.get_job(job_id, other)
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_llm_backtest_job_http_routes_reject_anonymous_and_hide_cross_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "_SETTINGS_FILE", tmp_path / "http-runs.json")
    monkeypatch.setattr(lab, "fetch_bars", lambda *a, **k: _async_value(_bars(50)))
    job_store._JOBS.clear()
    job_store._CANCEL_EVENTS.clear()
    alice = create_access_token({"sub": "alice-http", "email": "alice-http@example.test"})
    bob = create_access_token({"sub": "bob-http", "email": "bob-http@example.test"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        payload = {"kind": "baseline", "baseline": "buy_hold", "symbol": "TEST"}
        anonymous = await client.post("/agentic-lab/backtest", json=payload)
        assert anonymous.status_code == 401
        created = await client.post("/agentic-lab/backtest", headers={"Authorization": f"Bearer {alice}"}, json=payload)
        assert created.status_code == 200, created.text
        job_id = created.json()["job_id"]
        foreign = await client.get(f"/agentic-lab/jobs/{job_id}", headers={"Authorization": f"Bearer {bob}"})
        assert foreign.status_code == 404
        owner = await client.get(f"/agentic-lab/jobs/{job_id}", headers={"Authorization": f"Bearer {alice}"})
        assert owner.status_code == 200, owner.text
        assert "meta" not in owner.json() and "owner_user_id" not in owner.text


@pytest.mark.asyncio
async def test_research_job_polls_and_cancels_are_owner_scoped(monkeypatch):
    job_id = job_store.create("strategy-research", {"owner_user_id": "alice", "objective": "private"})
    owner = User(id="alice", email="alice@example.test")
    stranger = User(id="bob", email="bob@example.test")
    response = await lab_api.get_research_job(job_id, owner)
    assert response["id"] == job_id and "meta" not in response and "owner_user_id" not in response
    with pytest.raises(HTTPException) as poll_error: await lab_api.get_research_job(job_id, stranger)
    with pytest.raises(HTTPException) as cancel_error: await lab_api.cancel_research_job(job_id, stranger)
    assert poll_error.value.status_code == cancel_error.value.status_code == 404
    assert (await lab_api.cancel_research_job(job_id, owner))["cancelled"]
    assert job_store.is_cancelled(job_id)


@pytest.mark.asyncio
async def test_research_loop_reserves_every_model_call_and_persists_private_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "_SETTINGS_FILE", tmp_path / "runs.json")
    monkeypatch.setattr(research, "_SETTINGS_FILE", tmp_path / "research.json")
    monkeypatch.setattr(lab_api.llm_svc, "canonical_provider", lambda _provider: {"id": "openrouter"})
    monkeypatch.setattr(lab_api.llm_svc, "resolve_endpoint", lambda _provider: ("https://example.test/v1", "configured"))
    monkeypatch.setattr(lab_api.llm_svc, "stored_settings", lambda _provider: {"models": ["test-model"]})
    monkeypatch.setattr(lab, "fetch_bars", lambda *a, **k: _async_value(_bars(50)))
    async def fake_run(spec, **kwargs):
        kwargs["reserve_model_call"]()
        kwargs["on_progress"] and await kwargs["on_progress"](1, 1, "decision")
        run = {"id": uuid.uuid4().hex, "metrics": {"total_return_pct": 1}, "owner_user_id": kwargs["owner_user_id"], "research_job_id": kwargs["research_job_id"], "research_iteration": kwargs["research_iteration"]}
        lab._store_run(run)
        return run
    monkeypatch.setattr(lab, "run_backtest", fake_run)
    calls = []
    async def chat(provider, model, messages, **kwargs): calls.append(messages); return "Use a simple trend filter and hold long above its average."
    monkeypatch.setattr(lab_api.llm_svc, "chat_once", chat)
    owner = User(id="alice", email="alice@example.test")
    created = await lab_api.create_research_job(lab_api.ResearchJobRequest(provider="openrouter", model="test-model", symbol="TEST", objective="Test a trend strategy", max_iterations=1, max_model_calls=2), owner)
    job_id = created["job_id"]
    for _ in range(200):
        job = job_store.get(job_id)
        if job and job["status"] in job_store.TERMINAL_STATUSES: break
        await asyncio.sleep(0.01)
    job = job_store.get(job_id)
    assert job["status"] == "succeeded" and job["model_calls"] == 2 and len(calls) == 1
    run = lab.list_runs()[0]
    assert run["owner_user_id"] == "alice" and run["research_job_id"] == job_id and run["research_iteration"] == 1
    assert research.list_docs("alice")[0]["research_job_id"] == job_id
    assert all("portfolio" not in str(messages).lower() and "broker" not in str(messages).lower() for messages in calls)


@pytest.mark.asyncio
async def test_research_job_cancelled_between_proposal_and_backtest(monkeypatch, tmp_path):
    monkeypatch.setattr(lab, "_SETTINGS_FILE", tmp_path / "runs.json")
    monkeypatch.setattr(research, "_SETTINGS_FILE", tmp_path / "research.json")
    monkeypatch.setattr(lab_api.llm_svc, "canonical_provider", lambda _provider: {"id": "openrouter"})
    monkeypatch.setattr(lab_api.llm_svc, "resolve_endpoint", lambda _provider: ("https://example.test/v1", "configured"))
    monkeypatch.setattr(lab_api.llm_svc, "stored_settings", lambda _provider: {"models": ["test-model"]})
    monkeypatch.setattr(lab, "fetch_bars", lambda *a, **k: _async_value(_bars(50)))
    owner = User(id="cancel-owner", email="cancel@example.test")
    proposal_calls = []
    async def chat(*args, **kwargs):
        proposal_calls.append(1)
        active_job = next(job for job in job_store.list_jobs(kind="strategy-research") if job["meta"].get("owner_user_id") == owner.id)
        assert job_store.cancel(active_job["id"])
        return "Use a moving-average trend strategy."
    monkeypatch.setattr(lab_api.llm_svc, "chat_once", chat)
    created = await lab_api.create_research_job(lab_api.ResearchJobRequest(provider="openrouter", model="test-model", symbol="TEST", objective="Test cancellation", max_iterations=1, max_model_calls=2), owner)
    job_id = created["job_id"]
    for _ in range(200):
        job = job_store.get(job_id)
        if job and job["status"] in job_store.TERMINAL_STATUSES: break
        await asyncio.sleep(0.01)
    job = job_store.get(job_id)
    assert job["status"] == "cancelled" and job["model_calls"] == 1
    assert len(proposal_calls) == 1 and lab.get_run_for_user(job_id, owner.id) is None
    assert not [doc for doc in research.list_docs(owner.id) if doc.get("research_job_id") == job_id]


@pytest.mark.asyncio
async def test_research_call_budget_callback_rejects_overflow(monkeypatch):
    bars = _bars(90); requested = []
    monkeypatch.setattr(lab, "llm_svc", type("LLM", (), {"resolve_endpoint": lambda _: None, "CATALOG_BY_ID": {"test": {}}, "chat_once": None})())
    async def chat(*args, **kwargs): requested.append(1); return '{"action":"flat","reason":"test"}'
    monkeypatch.setattr(lab.llm_svc, "chat_once", chat)
    count = 0
    def reserve():
        nonlocal count
        if count >= 1: raise RuntimeError("call cap")
        count += 1
    with pytest.raises(RuntimeError, match="call cap"):
        await lab.llm_targets(bars, provider="test", model="m", prompt="p", step=2, symbol="TEST", tf="1d", capital=1000, reserve_model_call=reserve)
    assert count == 1 and len(requested) == 1
