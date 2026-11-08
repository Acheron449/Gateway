"""Static contract for the owner-scoped Supabase schema (SRS §7, DR-1…DR-5).

Runtime proof still needs a live project with two real accounts (anon sees
zero rows; account B cannot read account A). What *can* be checked offline is
the policy shape that runtime proof depends on, so a future table or policy
edit cannot quietly ship a permissive or unguarded row.
"""

from __future__ import annotations

import re
from pathlib import Path

TABLE_RE = re.compile(r"create table if not exists (\w+)", re.IGNORECASE)
RLS_RE = re.compile(r"alter table (\w+)\s+enable row level security", re.IGNORECASE)
POLICY_RE = re.compile(r"create policy (\w+)\s+on\s+(\w+)(.*?);", re.IGNORECASE | re.DOTALL)

EXPECTED_TABLES = {
    "profiles",
    "preferences",
    "notice_acceptances",
    "strategies",
    "strategy_versions",
    "backtest_runs",
    "portfolios",
    "orders",
    "fills",
    "positions",
    "bot_runs",
    "bot_logs",
}

# Child rows must derive ownership from their parent, never from a
# client-supplied owner column.
CHILD_PARENTS = {
    "strategy_versions": "strategies",
    "orders": "portfolios",
    "fills": "orders",
    "positions": "portfolios",
    "bot_logs": "bot_runs",
}


def _schema_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "supabase" / "schema.sql"
        if candidate.is_file():
            return candidate
    raise AssertionError("supabase/schema.sql not found above the tests directory")


SQL = _schema_path().read_text(encoding="utf-8")
COMPACT = " ".join(SQL.lower().split())


def _tables() -> set[str]:
    return {match.group(1) for match in TABLE_RE.finditer(SQL)}


def _rls_tables() -> set[str]:
    return {match.group(1) for match in RLS_RE.finditer(SQL)}


def _policies() -> list[tuple[str, str, str]]:
    return [
        (match.group(1), match.group(2), " ".join(match.group(3).split()))
        for match in POLICY_RE.finditer(SQL)
    ]


def test_every_table_is_known_and_has_row_level_security_enabled() -> None:
    tables = _tables()
    assert tables == EXPECTED_TABLES  # a new table must be added here, with RLS
    assert _rls_tables() == tables


def test_every_table_has_exactly_one_owner_policy() -> None:
    policies = _policies()
    covered = [table for _, table, _ in policies]
    assert sorted(covered) == sorted(EXPECTED_TABLES)
    assert len(covered) == len(set(covered))


def test_policies_filter_reads_and_validate_writes_against_auth_uid() -> None:
    for name, table, body in _policies():
        lowered = body.lower()
        assert "auth.uid()" in lowered, f"{name} on {table} is not owner-scoped"
        assert "using" in lowered, f"{name} on {table} does not filter reads"
        assert "with check" in lowered, f"{name} on {table} does not validate writes"


def test_child_policies_inherit_ownership_through_the_parent() -> None:
    bodies = {table: body for _, table, body in _policies()}
    for child, parent in CHILD_PARENTS.items():
        body = bodies[child].lower()
        assert "exists" in body, f"{child} must inherit ownership via exists(...)"
        assert parent in body, f"{child} must derive ownership from {parent}"
        assert "owner_id = auth.uid()" in body


def test_no_policy_is_permissive_or_granted_to_anon_or_public() -> None:
    assert "to anon" not in COMPACT
    assert "to public" not in COMPACT
    assert "using (true)" not in COMPACT
    assert "with check (true)" not in COMPACT
