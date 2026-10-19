from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.v1 import strategies
from app.models import (
    Assumptions,
    EntryRule,
    StrategySpec,
    Timeframe,
    canonical_strategy_payload,
    compute_strategy_content_hash,
)
from app.services import database


def make_spec(**updates) -> StrategySpec:
    values = {
        "strategy_id": "strategy-1",
        "version": 1,
        "name": "Example",
        "universe": ["AAPL", "MSFT"],
        "timeframe": Timeframe.H1,
        "entry_rules": [EntryRule(id="entry-1", condition={"indicator": "RSI", "threshold": 30})],
        "assumptions": Assumptions(commission_per_share=Decimal("0.005")),
    }
    values.update(updates)
    return StrategySpec(**values)


def test_hash_is_deterministic_and_excludes_nonsemantic_metadata() -> None:
    first = make_spec()
    second = make_spec(
        strategy_id="other-id",
        version=8,
        name="renamed",
        description="different description",
        tags=["tag"],
        created_by="someone",
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    assert compute_strategy_content_hash(first) == compute_strategy_content_hash(second)


def test_object_key_order_and_decimal_number_normalization() -> None:
    left = make_spec(entry_rules=[EntryRule(id="e", condition={"a": Decimal("1.00"), "b": True})])
    right = make_spec(entry_rules=[EntryRule(id="e", condition={"b": True, "a": 1.0})])
    assert canonical_strategy_payload(left) == canonical_strategy_payload(right)
    assert compute_strategy_content_hash(left) == compute_strategy_content_hash(right)


def test_unicode_nfc_normalizes_values_and_rejects_colliding_keys() -> None:
    composed = make_spec(universe=["Café"])
    decomposed = make_spec(universe=["Cafe\u0301"])
    assert compute_strategy_content_hash(composed) == compute_strategy_content_hash(decomposed)
    collision = make_spec(entry_rules=[EntryRule(id="e", condition={"é": 1, "e\u0301": 2})])
    with pytest.raises(ValueError, match="NFC-colliding"):
        compute_strategy_content_hash(collision)


def test_universe_and_set_like_lists_are_unordered_but_rule_lists_are_ordered() -> None:
    left = make_spec(universe=["MSFT", "AAPL", "AAPL"], session_rules=[])
    right = make_spec(universe=["AAPL", "MSFT"])
    assert compute_strategy_content_hash(left) == compute_strategy_content_hash(right)

    rule_a = EntryRule(id="a", condition={"indicator": "RSI", "threshold": 30})
    rule_b = EntryRule(id="b", condition={"indicator": "MACD", "cross": True})
    forward = make_spec(entry_rules=[rule_a, rule_b])
    reverse = make_spec(entry_rules=[rule_b, rule_a])
    assert compute_strategy_content_hash(forward) != compute_strategy_content_hash(reverse)

    sessions = make_spec(session_rules=[{"id": "s", "allowed_sessions": ["RTH", "PRE"]}])
    sessions_reordered = make_spec(session_rules=[{"id": "different", "allowed_sessions": ["PRE", "RTH", "RTH"]}])
    assert compute_strategy_content_hash(sessions) == compute_strategy_content_hash(sessions_reordered)


def test_rule_labels_and_ids_excluded_but_semantic_fields_change_hash() -> None:
    first = make_spec(entry_rules=[EntryRule(id="one", description="a", condition={"x": 1})])
    renamed = make_spec(entry_rules=[EntryRule(id="two", description="b", condition={"x": 1})])
    changed = make_spec(entry_rules=[EntryRule(id="one", condition={"x": 2})])
    assert compute_strategy_content_hash(first) == compute_strategy_content_hash(renamed)
    assert compute_strategy_content_hash(first) != compute_strategy_content_hash(changed)


def test_text_only_executable_rule_fails_closed() -> None:
    spec = make_spec(entry_rules=[EntryRule(id="e", condition={}, text="buy when it looks good")])
    with pytest.raises(ValueError, match="structured semantic fields"):
        compute_strategy_content_hash(spec)


def test_hash_assertion_is_verified_and_not_in_model_dump() -> None:
    spec = make_spec()
    digest = compute_strategy_content_hash(spec)
    asserted = make_spec(content_hash=digest)
    assert asserted.model_dump(mode="json").get("content_hash") is None
    with pytest.raises(ValidationError, match="content_hash"):
        make_spec(content_hash="0" * 64)


def test_hash_distinguishes_bool_string_and_number() -> None:
    boolean = make_spec(entry_rules=[EntryRule(id="e", condition={"value": True})])
    numeric = make_spec(entry_rules=[EntryRule(id="e", condition={"value": 1})])
    string = make_spec(entry_rules=[EntryRule(id="e", condition={"value": "1"})])
    assert len({compute_strategy_content_hash(boolean), compute_strategy_content_hash(numeric), compute_strategy_content_hash(string)}) == 3


def test_non_finite_numbers_are_rejected() -> None:
    spec = make_spec(entry_rules=[EntryRule(id="e", condition={"value": float("nan")})])
    with pytest.raises(ValueError, match="NaN or Infinity"):
        compute_strategy_content_hash(spec)


def test_legacy_strategy_rows_keep_null_hash_after_schema_upgrade(monkeypatch, tmp_path) -> None:
    path = tmp_path / "strategies.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", path)
    monkeypatch.setattr(strategies, "get_connection", database.get_connection)
    monkeypatch.setattr(strategies, "init_db", database.init_db)
    # Use an isolated schema with a legacy row to exercise the nullable upgrade.
    def scenario():
        with database.get_connection() as conn:
            conn.execute("CREATE TABLE strategies (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, status TEXT, current_version INTEGER, tags TEXT, created_at TEXT, updated_at TEXT)")
            conn.execute("CREATE TABLE strategy_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT NOT NULL, version INTEGER NOT NULL, spec TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(strategy_id, version))")
            conn.execute("INSERT INTO strategies VALUES ('legacy', 'Legacy', '', 'draft', 1, '[]', 'now', 'now')")
            conn.execute("INSERT INTO strategy_versions (strategy_id, version, spec, created_at) VALUES ('legacy', 1, ?, 'now')", (json.dumps(make_spec().model_dump(mode="json")),))
            conn.commit()
        strategies._get_strategy_table()
        with database.get_connection() as conn:
            legacy = conn.execute("SELECT content_hash FROM strategy_versions WHERE strategy_id='legacy'").fetchone()
        assert legacy[0] is None


def test_create_strategy_stores_hash_separately_and_excludes_it_from_spec(monkeypatch, tmp_path) -> None:
    path = tmp_path / "created.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", path)
    monkeypatch.setattr(strategies, "get_connection", database.get_connection)
    monkeypatch.setattr(strategies, "init_db", database.init_db)
    strategies._get_strategy_table()
    request = strategies.StrategyCreateRequest(
        name="Created",
        universe=["AAPL"],
        entry_rules=[{"id": "entry", "condition": {"indicator": "RSI", "threshold": 30}}],
    )
    asyncio.run(strategies.create_strategy(request))
    with database.get_connection() as conn:
        row = conn.execute("SELECT spec, content_hash FROM strategy_versions").fetchone()
    assert row["content_hash"] == compute_strategy_content_hash(StrategySpec(**json.loads(row["spec"])))
    assert "content_hash" not in json.loads(row["spec"])


def test_create_strategy_version_allocates_concurrently_without_duplicates(monkeypatch, tmp_path) -> None:
    path = tmp_path / "concurrent.sqlite3"
    monkeypatch.setattr(database, "DB_PATH", path)
    monkeypatch.setattr(strategies, "get_connection", database.get_connection)
    monkeypatch.setattr(strategies, "init_db", database.init_db)
    strategies._get_strategy_table()
    with database.get_connection() as conn:
        conn.execute("INSERT INTO strategies (id, name, description, status, current_version, tags, created_at, updated_at) VALUES ('race', 'Race', '', 'draft', 1, '[]', 'now', 'now')")
        conn.execute("INSERT INTO strategy_versions (strategy_id, version, spec, created_at) VALUES ('race', 1, ?, 'now')", (json.dumps(make_spec(strategy_id="race").model_dump(mode="json")),))
        conn.commit()

    incoming = make_spec(strategy_id="race")
    def create():
        return asyncio.run(strategies.create_strategy_version("race", incoming))

    with ThreadPoolExecutor(max_workers=2) as pool:
        versions = list(pool.map(lambda _index: create(), range(2)))
    assert sorted(response.version for response in versions) == [2, 3]
    with database.get_connection() as conn:
        rows = conn.execute("SELECT version, content_hash, spec FROM strategy_versions WHERE strategy_id='race' ORDER BY version").fetchall()
    assert [row["version"] for row in rows] == [1, 2, 3]
    for row in rows[1:]:
        assert row["content_hash"]
        assert "content_hash" not in json.loads(row["spec"])
