"""P4 exit gate: receipts, deterministic replay, OOS, retention, CSV."""

from __future__ import annotations

import asyncio
import math
import random

import pytest
from fastapi import HTTPException

from app.api.v1.backtest import (
    BacktestRunRequest,
    _csv_safe,
    compare_runs,
    download_run_csv,
    get_run,
    run_backtest,
)
from app.auth import User
from app.services import database
from app.services.backtest_engine import canon_json, run_backtest as run_engine

USER = User(id="owner-1", email="owner@example.com", name="Owner", subject="owner-1")
OTHER = User(id="owner-2", email="other@example.com", name="Other", subject="owner-2")


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "p4.db")
    database.init_db()
    yield


def make_bars(n: int = 400, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    price = 100.0
    t0 = 1_700_000_000
    bars = []
    for i in range(n):
        price *= 1 + 0.0015 * math.sin(i / 9) + rng.uniform(-0.004, 0.004) + 0.0006
        bars.append(
            {
                "time": t0 + i * 3600,
                "open": price * 0.999,
                "high": price * 1.004,
                "low": price * 0.996,
                "close": price,
                "volume": 1000 + i,
            }
        )
    return bars


def make_spec(fast: int = 5, slow: int = 12, amount: float = 0.5) -> dict:
    return {
        "asset_universe": ["TEST"],
        "timeframe": "1h",
        "entry": {"condition": "sma_fast_crosses_above_sma_slow", "params": {"fast": fast, "slow": slow}},
        "exit": {"condition": "sma_fast_crosses_below_sma_slow", "params": {}},
        "sizing": {"mode": "pct_equity", "amount": amount},
        "invalidation": {"stop_loss": None},
        "assumptions": {"commission": 0.0},
    }


def _payload(**overrides) -> BacktestRunRequest:
    data = {
        "strategy": make_spec(),
        "symbol": "TEST",
        "timeframe": "1h",
        "initial_capital": 100_000.0,
        "seed": 11,
        "oos_ratio": 0.3,
        "bars": make_bars(),
    }
    data.update(overrides)
    return BacktestRunRequest(**data)


def test_same_inputs_produce_byte_identical_metrics():
    bars = make_bars()
    first = run_engine(spec=make_spec(), bars=bars, symbol="TEST", timeframe="1h")
    second = run_engine(spec=make_spec(), bars=bars, symbol="TEST", timeframe="1h")
    assert canon_json(first["metrics"]) == canon_json(second["metrics"])
    assert canon_json(first["trades"]) == canon_json(second["trades"])
    assert first["data_hash"] == second["data_hash"]


def test_receipt_carries_everything_needed_to_replay():
    result = run_engine(spec=make_spec(), bars=make_bars(), symbol="TEST", timeframe="1h")
    receipt = result["receipt"]
    for key in (
        "engine_version",
        "spec",
        "symbol",
        "timeframe",
        "window",
        "data_hash",
        "spec_hash",
        "costs",
        "seed",
        "initial_capital",
        "oos_ratio",
        "created_at",
    ):
        assert key in receipt, key


def test_oos_is_reported_separately_and_can_be_disabled():
    result = run_engine(spec=make_spec(), bars=make_bars(), symbol="TEST", timeframe="1h", oos_ratio=0.3)
    assert result["oos"]["evaluated"] is True
    assert result["oos"]["metrics"]["trades"] >= 0
    assert result["is_metrics"] != result["oos"]["metrics"]

    skipped = run_engine(spec=make_spec(), bars=make_bars(), symbol="TEST", timeframe="1h", oos_ratio=0)
    assert skipped["oos"]["evaluated"] is False
    assert "oos_ratio was 0" in skipped["oos"]["reason"]


def test_higher_costs_reduce_net_pnl(temp_db):
    base = asyncio.run(run_backtest(_payload(), USER))
    dearer = asyncio.run(
        run_backtest(
            _payload(
                costs={
                    "commission_per_trade": 25.0,
                    "half_spread_bps": 20.0,
                    "slippage_bps": 20.0,
                }
            ),
            USER,
        )
    )
    assert base["metrics"]["trades"] > 0, "fixture must trade for the cost check to mean anything"
    assert dearer["metrics"]["net_pnl"] < base["metrics"]["net_pnl"]


def test_replay_from_receipt_reproduces_metrics(temp_db):
    bars = make_bars()
    first = asyncio.run(run_backtest(_payload(bars=bars), USER))
    replay = asyncio.run(
        run_backtest(BacktestRunRequest(receipt=first["receipt"], bars=bars), USER)
    )
    assert replay["data_hash"] == first["data_hash"]
    assert canon_json(replay["metrics"]) == canon_json(first["metrics"])
    assert canon_json(replay["trades"]) == canon_json(first["trades"])


def test_replay_refuses_changed_data(temp_db):
    bars = make_bars()
    first = asyncio.run(run_backtest(_payload(bars=bars), USER))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            run_backtest(
                BacktestRunRequest(receipt=first["receipt"], bars=make_bars(seed=99)), USER
            )
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "data_changed"


def test_runs_are_owner_scoped(temp_db):
    run = asyncio.run(run_backtest(_payload(), USER))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_run(run["run_id"], OTHER))
    assert exc.value.status_code == 404


def test_retention_caps_at_fifty_per_owner(temp_db):
    for i in range(55):
        database.save_backtest_receipt(
            run_id=f"run-{i}",
            owner_id=USER.id,
            status="completed",
            symbol="TEST",
            timeframe="1h",
            data_hash=f"hash-{i}",
            receipt={"i": i},
            metrics={"net_pnl": i},
        )
    assert len(database.list_backtest_receipts(USER.id)) == database.RECEIPT_RETENTION
    assert database.list_backtest_receipts(USER.id)[0]["receipt"]["i"] == 54


def test_csv_escapes_formula_injection(temp_db):
    run = asyncio.run(run_backtest(_payload(), USER))
    response = asyncio.run(download_run_csv(run["run_id"], USER))
    body = response.body.decode()
    assert body.startswith("section,key,value")
    assert "metrics,net_pnl" in body

    assert _csv_safe("=1+1") == "'=1+1"
    assert _csv_safe("+42") == "'+42"
    assert _csv_safe("-42") == "'-42"
    assert _csv_safe("@SUM(A1)") == "'@SUM(A1)"
    assert _csv_safe("AAPL") == "AAPL"


def test_compare_returns_metric_deltas(temp_db):
    left = asyncio.run(run_backtest(_payload(), USER))
    right = asyncio.run(
        run_backtest(
            _payload(costs={"commission_per_trade": 30.0, "half_spread_bps": 15.0, "slippage_bps": 15.0}),
            USER,
        )
    )
    comparison = asyncio.run(compare_runs(type("P", (), {"run_ids": [left["run_id"], right["run_id"]]})(), USER))
    assert comparison["deltas"]["net_pnl"] < 0
    assert comparison["left"]["run_id"] == left["run_id"]


def test_receipts_are_insert_only(temp_db):
    """NFR-18: a re-used run id is refused and the stored receipt is unchanged."""
    kwargs = dict(
        run_id="run-immutable",
        owner_id=USER.id,
        status="completed",
        symbol="TEST",
        timeframe="1h",
        data_hash="hash-1",
        receipt={"version": 1},
        metrics={"net_pnl": 1},
    )
    database.save_backtest_receipt(**kwargs)

    with pytest.raises(ValueError, match="already exists"):
        database.save_backtest_receipt(
            **{**kwargs, "data_hash": "hash-2", "receipt": {"version": 2}, "metrics": {"net_pnl": 999}}
        )

    stored = database.get_backtest_receipt("run-immutable", USER.id)
    assert stored is not None
    assert stored["receipt"] == {"version": 1}
    assert stored["data_hash"] == "hash-1"
    assert stored["metrics"] == {"net_pnl": 1}
