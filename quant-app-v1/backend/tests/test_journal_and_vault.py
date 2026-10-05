from __future__ import annotations

import pytest
from uuid import uuid4

from app.services import journal_log, secrets_vault
from app.services.database import get_connection


def _sym() -> str:
    return f"JT{uuid4().hex[:6].upper()}"


class TestJournalAutoLog:
    def test_buy_then_sell_roundtrip_closes_with_pnl(self):
        sym = _sym()
        buy_fill = f"fill-{uuid4().hex}"
        sell_fill = f"fill-{uuid4().hex}"

        entry_id = journal_log.log_fill(
            buy_fill, sym, "buy", 10, 100.0, source="paper", note="open long"
        )
        assert entry_id is not None

        # Dedupe: the same fill id must never be applied twice.
        assert journal_log.log_fill(buy_fill, sym, "buy", 10, 100.0, source="paper") is None

        closed_id = journal_log.log_fill(
            sell_fill, sym, "sell", 10, 110.0, source="paper", note="close long"
        )
        assert closed_id == entry_id

        with get_connection() as conn:
            row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
        assert row is not None
        assert row["status"] == "closed"
        assert row["source"] == "paper"
        assert row["pnl"] == pytest.approx((110.0 - 100.0) * 10)
        assert row["fill_id"] == buy_fill

        with get_connection() as conn:
            conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
            conn.execute("DELETE FROM journal_fill_log WHERE fill_id IN (?, ?)", (buy_fill, sell_fill))
            conn.commit()

    def test_partial_exit_shrinks_the_open_entry(self):
        sym = _sym()
        entry_id = journal_log.log_fill(
            f"fill-{uuid4().hex}", sym, "buy", 10, 50.0, source="paper"
        )
        journal_log.log_fill(f"fill-{uuid4().hex}", sym, "sell", 4, 55.0, source="paper")

        with get_connection() as conn:
            row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
        assert row["status"] == "open"
        assert row["quantity"] == pytest.approx(6.0)

        with get_connection() as conn:
            conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
            conn.execute(
                "DELETE FROM journal_fill_log WHERE entry_id = ?", (entry_id,)
            )
            conn.commit()

    def test_paper_and_actual_sources_are_tracked_independently(self):
        sym = _sym()
        paper = journal_log.log_fill(f"fill-{uuid4().hex}", sym, "buy", 1, 10.0, source="paper")
        actual = journal_log.log_fill(f"fill-{uuid4().hex}", sym, "buy", 1, 10.0, source="actual")
        assert paper and actual and paper != actual

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT source FROM journal_entries WHERE symbol = ?", (sym,)
            ).fetchall()
        assert sorted(r["source"] for r in rows) == ["actual", "paper"]

        with get_connection() as conn:
            conn.execute("DELETE FROM journal_entries WHERE symbol = ?", (sym,))
            conn.execute(
                "DELETE FROM journal_fill_log WHERE entry_id IN (?, ?)", (paper, actual)
            )
            conn.commit()

    def test_short_open_when_no_opposite_entry_exists(self):
        sym = _sym()
        entry_id = journal_log.log_fill(
            f"fill-{uuid4().hex}", sym, "sell", 5, 20.0, source="paper"
        )
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
        assert row["side"] == "sell"
        assert row["status"] == "open"

        # A buy now covers the short and realises PnL.
        journal_log.log_fill(f"fill-{uuid4().hex}", sym, "buy", 5, 18.0, source="paper")
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
        assert row["status"] == "closed"
        assert row["pnl"] == pytest.approx((20.0 - 18.0) * 5)

        with get_connection() as conn:
            conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
            conn.execute("DELETE FROM journal_fill_log WHERE entry_id = ?", (entry_id,))
            conn.commit()


class TestJournalApiSourceFilter:
    def test_create_and_filter_by_source(self):
        # The venv's TestClient/httpx pair is incompatible, so exercise the
        # route functions directly (same code paths FastAPI would call).
        import asyncio
        from app.api.v1.journal import (
            JournalEntryCreate,
            create_journal_entry,
            delete_journal_entry,
            get_journal_stats,
            list_journal_entries,
        )

        async def run():
            created = await create_journal_entry(
                JournalEntryCreate(
                    symbol=_sym(),
                    side="buy",
                    quantity=1,
                    entry_price=10,
                    hypothesis="source filter test",
                    source="actual",
                )
            )
            kwargs = dict(
                status=None, symbol=None, start_date=None, end_date=None,
                tag=None, limit=100, offset=0,
            )
            actual = await list_journal_entries(source="actual", **kwargs)
            manual = await list_journal_entries(source="manual", **kwargs)
            stats = await get_journal_stats(source="actual")
            return created, actual, manual, stats

        created, actual, manual, stats = asyncio.run(run())
        try:
            assert created.source == "actual"
            assert created.id in [e["id"] for e in actual["entries"]]
            assert created.id not in [e["id"] for e in manual["entries"]]
            assert stats.total_trades >= 1
        finally:
            asyncio.run(delete_journal_entry(created.id))


class TestSecretsVault:
    @pytest.fixture(autouse=True)
    def isolated_vault(self, tmp_path, monkeypatch):
        monkeypatch.setattr(secrets_vault, "_VAULT_FILE", tmp_path / "secrets.vault")
        monkeypatch.setattr(secrets_vault, "_VAULT_KEY_FILE", tmp_path / "secrets.vault.key")
        # Force the locally generated key so the test never depends on env.
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", "")
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY_FILE", "")

    def test_roundtrip_is_encrypted_at_rest(self):
        name = f"test/{uuid4().hex[:8]}"
        secret_value = f"sk-live-{uuid4().hex}"
        meta = secrets_vault.set_secret(name, secret_value, note="pytest")
        assert meta["name"] == name

        # Ciphertext on disk — plaintext never appears in the file.
        raw = secrets_vault._VAULT_FILE.read_text(encoding="utf-8")
        assert secret_value not in raw
        assert "cipher" in raw

        assert secrets_vault.get_secret(name) == secret_value
        listed = secrets_vault.list_secrets()
        entry = next(s for s in listed if s["name"] == name)
        assert "cipher" not in entry and "value" not in entry
        assert entry["length"] == len(secret_value)

        assert secrets_vault.delete_secret(name) is True
        assert secrets_vault.get_secret(name) is None
        assert secrets_vault.delete_secret(name) is False

    def test_empty_value_rejected(self):
        with pytest.raises(secrets_vault.VaultError):
            secrets_vault.set_secret("bad", "   ")


class TestAiTradingScoring:
    def test_momentum_scores_uptrend_long(self):
        from app.services.ai_trading import score_symbol

        closes = [100 + i * 0.5 for i in range(30)]
        signal, confidence, reason = score_symbol(closes, "momentum")
        assert signal == 1
        assert 0 < confidence <= 1
        assert "momentum" in reason

    def test_mean_reversion_fades_a_spike(self):
        from app.services.ai_trading import score_symbol

        closes = [100.0] * 25
        closes[-1] = 120.0
        signal, confidence, _ = score_symbol(closes, "mean_reversion")
        assert signal == -1
        assert confidence > 0

    def test_insufficient_history_is_neutral(self):
        from app.services.ai_trading import score_symbol

        signal, confidence, _ = score_symbol([100.0, 101.0], "momentum")
        assert signal == 0
        assert confidence == 0.0

    def test_config_roundtrip_and_clamping(self, tmp_path, monkeypatch):
        from app.services import ai_trading

        monkeypatch.setattr(ai_trading, "_CONFIG_FILE", tmp_path / "ai_trading.json")
        saved = ai_trading.save_config(
            {
                "symbols": "spy, qqq , ",
                "confidence_threshold": 5,  # out of range → clamped
                "cycle_seconds": 1,
                "strategy": "nonsense",
            }
        )
        assert saved["symbols"] == ["SPY", "QQQ"]
        assert saved["confidence_threshold"] == 1.0
        assert saved["cycle_seconds"] == 15
        assert saved["strategy"] == "momentum"

        loaded = ai_trading.get_config()
        assert loaded["symbols"] == ["SPY", "QQQ"]
