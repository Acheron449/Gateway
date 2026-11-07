"""P4 exit gate: a bot starts, logs decisions, stops, and obeys the limits."""

from __future__ import annotations

import pytest

from app.services import bot_runner, database, kill_switch
from app.services.bot_runner import BotRunError

OWNER = "owner-1"
OTHER = "owner-2"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "p4-bots.db")
    database.init_db()
    kill_switch.reset(reset_by="test")
    database.create_portfolio("bot-portfolio", OWNER, 100_000.0)
    yield
    kill_switch.reset(reset_by="test")


def make_spec() -> dict:
    return {
        "asset_universe": ["TEST"],
        "timeframe": "1h",
        "entry": {"condition": "sma_fast_crosses_above_sma_slow", "params": {"fast": 3, "slow": 6}},
        "exit": {"condition": "sma_fast_crosses_below_sma_slow", "params": {}},
        "sizing": {"mode": "pct_equity", "amount": 0.1},
        "invalidation": {"stop_loss": None},
        "assumptions": {"commission": 0.0},
    }


def make_bars(rising: bool = True, n: int = 120) -> list[dict]:
    price = 100.0
    bars = []
    for i in range(n):
        price *= 1.004 if rising else 0.996
        bars.append(
            {
                "time": 1_700_000_000 + i * 3600,
                "open": price,
                "high": price * 1.002,
                "low": price * 0.998,
                "close": price,
                "volume": 1000,
            }
        )
    return bars


def _create(**overrides) -> dict:
    payload = {
        "strategy": make_spec(),
        "instrument": "TEST",
        "timeframe": "1h",
        "portfolio_id": "bot-portfolio",
        "interval_seconds": 60,
        "max_iterations": 2,
    }
    payload.update(overrides)
    return bot_runner.create_run(OWNER, payload)


def test_interval_below_one_minute_is_refused(temp_db):
    with pytest.raises(BotRunError) as exc:
        _create(interval_seconds=30)
    assert exc.value.status_code == 400
    assert "60" in str(exc.value)


def test_live_feed_is_refused(temp_db):
    with pytest.raises(BotRunError) as exc:
        _create(live=True)
    assert exc.value.status_code == 400
    with pytest.raises(BotRunError):
        _create(source="live")


def test_at_most_two_concurrent_runs(temp_db):
    _create(max_iterations=5)
    _create(max_iterations=5)
    with pytest.raises(BotRunError) as exc:
        _create(max_iterations=5)
    assert exc.value.status_code == 429


def test_run_once_logs_a_decision_and_stops_at_the_iteration_bound(temp_db):
    run = _create(max_iterations=1)
    decision = bot_runner.run_once(run["id"], bars=make_bars(rising=True))
    assert decision is not None
    assert decision["action"] in {"buy", "hold", "skipped"}
    assert decision["inputs"]["close"] > 0

    log = bot_runner.decisions(OWNER, run["id"])
    assert len(log) == 1
    assert log[0]["risk_verdict"] in {"passed", "blocked"} or log[0]["signal"]

    state = database.get_bot_run(run["id"])
    assert state["iterations"] == 1
    assert state["status"] == "stopped"
    assert state["stop_reason"] == "max_iterations"


def test_bot_orders_use_the_shared_admission_path(temp_db):
    run = _create(max_iterations=2)
    bot_runner.run_once(run["id"], bars=make_bars(rising=True))
    portfolio = database.get_portfolio("bot-portfolio")
    # Either the signal fired and an order was reserved, or the bot chose to
    # hold — but it can never write outside the admission path.
    for order in portfolio["open_orders"]:
        assert order["reserved_amount"] >= 0
    decisions = bot_runner.decisions(OWNER, run["id"])
    assert decisions and "risk_verdict" in decisions[0]


def test_kill_switch_blocks_bot_orders_but_still_logs(temp_db, monkeypatch):
    run = _create(max_iterations=2)
    # Force an entry so the tick actually reaches admission; a flat bar series
    # would otherwise hold and never exercise the gate.
    monkeypatch.setattr(
        bot_runner,
        "latest_signal",
        lambda spec, bars: {
            "signal": "long",
            "action": "enter",
            "inputs": {"close": bars[-1]["close"]},
            "params": {"position_pct": 0.1},
        },
    )
    from app.services.risk_engine import RiskConfig, RiskEngine

    relaxed = RiskEngine(RiskConfig(max_concentration_instrument=1.0, max_gross_exposure=10.0, max_net_exposure=10.0))
    monkeypatch.setattr("app.services.order_admission.get_risk_engine", lambda: relaxed)
    kill_switch.activate("halt for test", activated_by="test")
    bot_runner.run_once(run["id"], bars=make_bars(rising=True))
    decisions = bot_runner.decisions(OWNER, run["id"])
    assert decisions
    assert "halt for test" in (decisions[0]["risk_verdict"] + str(decisions[0]["detail"]))
    assert database.get_portfolio("bot-portfolio")["open_orders"] == []


def test_stop_is_owner_scoped(temp_db):
    run = _create(max_iterations=2)
    with pytest.raises(BotRunError) as exc:
        bot_runner.stop_run(OTHER, run["id"])
    assert exc.value.status_code == 404
    stopped = bot_runner.stop_run(OWNER, run["id"])
    assert stopped["status"] == "stopped"
    assert stopped["stop_reason"] == "stopped_by_user"


def test_stopped_runs_do_not_tick(temp_db):
    run = _create(max_iterations=5)
    bot_runner.stop_run(OWNER, run["id"])
    assert bot_runner.run_once(run["id"], bars=make_bars()) is None
