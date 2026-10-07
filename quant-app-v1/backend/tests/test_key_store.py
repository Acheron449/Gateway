"""Tests for durable (Supabase) storage of encrypted provider API keys.

Before this, keys saved from the UI lived only in the per-instance settings
file — on Vercel that is ephemeral ``/tmp``, so keys vanished when the
instance recycled. ``key_store`` now mirrors ``database.py``'s Supabase
mode: ciphertext-only rows in ``gateway_provider_keys`` (RLS denied to
anon/authenticated, reachable only through secret-gated SECURITY DEFINER
RPCs), Supabase authoritative when the trio is configured, local file as
the read fallback. Reads never raise; writes raise ``RuntimeError`` so
routes answer 503 instead of pretending a key was saved.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from app.api.main import app
from app.auth import User, get_current_user
from app.providers import registry
from app.services import key_store
from app.services import llm_providers as llm_svc


@pytest.fixture(autouse=True)
def _clean_key_store():
    key_store.reset_cache()
    yield
    key_store.reset_cache()


@pytest.fixture
def supabase_trio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example-project.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "sb_publishable_test")
    monkeypatch.setenv("SUPABASE_RPC_SECRET", "test-rpc-secret")


@pytest.fixture
def no_supabase(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "")
    monkeypatch.setenv("SUPABASE_KEY", "")
    monkeypatch.setenv("SUPABASE_RPC_SECRET", "")


class _Rpc:
    """Stand-in for database._sb_rpc: records calls, simulates a tiny store."""

    def __init__(
        self,
        rows: list[dict] | None = None,
        fail: bool = False,
        store: str = "market",
        fail_fns: set[str] | None = None,
    ) -> None:
        self.fail = fail
        self.fail_fns = fail_fns or set()
        self.calls: list[tuple[str, dict]] = []
        self.rows: dict[tuple[str, str], dict] = {
            (store, str(r["name"])): dict(r) for r in (rows or [])
        }

    def __call__(self, fn: str, payload: dict):
        self.calls.append((fn, payload))
        if self.fail or fn in self.fail_fns:
            raise RuntimeError(f"Supabase RPC {fn} unreachable: connection refused")
        if fn == "gw_list_provider_keys":
            store = payload["p_store"]
            return [r for (s, _), r in self.rows.items() if s == store]
        if fn == "gw_upsert_provider_key":
            self.rows[(payload["p_store"], payload["p_name"])] = {
                "name": payload["p_name"],
                "ciphertext": payload.get("p_ciphertext"),
                "payload": payload.get("p_payload"),
            }
            return None
        if fn == "gw_delete_provider_key":
            self.rows.pop((payload["p_store"], payload["p_name"]), None)
            return None
        return None

    def fns(self) -> list[str]:
        return [fn for fn, _ in self.calls]


def _use_rpc(monkeypatch: pytest.MonkeyPatch, rpc: _Rpc) -> None:
    monkeypatch.setattr(key_store, "_sb_rpc", rpc)


async def fetch(path: str, method: str = "GET", body: dict | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        kwargs = {"json": body} if body is not None else {}
        return await client.request(method, path, **kwargs)


@pytest.fixture
def auth_user():
    app.dependency_overrides[get_current_user] = lambda: User(
        id="u-test", email="key-store@test.local", name="Key Store Test"
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


class TestKeyStoreBasics:
    def test_disabled_without_supabase_trio_never_touches_network(
        self, no_supabase: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(fn: str, payload: dict):
            raise AssertionError("network must not be used when the trio is unset")

        monkeypatch.setattr(key_store, "_sb_rpc", _boom)
        assert key_store.enabled() is False
        assert key_store.load("market") is None
        key_store.save("market", "Finnhub", "gAAAA")  # no-op, no raise
        key_store.delete("market", "Finnhub")  # no-op, no raise

    def test_load_caches_snapshot_within_ttl(
        self, supabase_trio: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rpc = _Rpc(rows=[{"name": "Finnhub", "ciphertext": "gAAAA-c", "payload": None}])
        _use_rpc(monkeypatch, rpc)

        first = key_store.load("market")
        second = key_store.load("market")

        assert first == {"Finnhub": {"ciphertext": "gAAAA-c", "payload": None}}
        assert second == first
        assert rpc.fns() == ["gw_list_provider_keys"]  # second read served from cache
        assert rpc.calls[0][1] == {"p_store": "market"}

    def test_load_failure_returns_none_then_stale_snapshot(
        self, supabase_trio: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Cold outage: no snapshot ⇒ None so callers fall back to their file.
        cold = _Rpc(fail=True)
        _use_rpc(monkeypatch, cold)
        assert key_store.load("market") is None

        # Warm outage: an expired snapshot keeps serving reads (degraded, never raising).
        key_store._cache["market"] = (
            time.monotonic() - (key_store._TTL + 1),
            {"Finnhub": {"ciphertext": "gAAAA-c", "payload": None}},
        )
        stale = _Rpc(fail=True)
        _use_rpc(monkeypatch, stale)
        assert key_store.load("market") == {
            "Finnhub": {"ciphertext": "gAAAA-c", "payload": None}
        }
        # Backed off: the failed refresh re-armed the TTL instead of hammering.
        assert key_store._cache["market"][0] == pytest.approx(time.monotonic(), abs=1.0)

    def test_save_and_delete_raise_on_rpc_failure(
        self, supabase_trio: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _use_rpc(monkeypatch, _Rpc(fail=True))
        with pytest.raises(RuntimeError, match="unreachable"):
            key_store.save("market", "Finnhub", "gAAAA-c")
        with pytest.raises(RuntimeError, match="unreachable"):
            key_store.delete("market", "Finnhub")

    def test_save_updates_cache_immediately(
        self, supabase_trio: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rpc = _Rpc()
        _use_rpc(monkeypatch, rpc)
        key_store.load("market")  # prime cache with []
        key_store.save("market", "Finnhub", "gAAAA-c", payload=None)

        assert rpc.calls[-1] == (
            "gw_upsert_provider_key",
            {
                "p_store": "market",
                "p_name": "Finnhub",
                "p_ciphertext": "gAAAA-c",
                "p_payload": None,
            },
        )
        assert key_store.load("market")["Finnhub"]["ciphertext"] == "gAAAA-c"

        key_store.delete("market", "Finnhub")
        assert rpc.calls[-1] == (
            "gw_delete_provider_key",
            {"p_store": "market", "p_name": "Finnhub"},
        )
        assert "Finnhub" not in key_store.load("market")


class TestRegistryIntegration:
    @pytest.fixture
    def local_registry_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        bundled = tmp_path / "settings"
        monkeypatch.setattr(registry, "_SETTINGS_DIR", bundled)
        monkeypatch.setattr(registry, "_SETTINGS_FILE", bundled / "provider_keys.json")
        return bundled

    def test_remote_is_authoritative_when_supabase_enabled(
        self,
        supabase_trio: None,
        local_registry_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Local file holds a stale copy; the durable row must win.
        local_registry_file.mkdir(parents=True, exist_ok=True)
        (local_registry_file / "provider_keys.json").write_text(
            json.dumps({"Finnhub": "stale-local-cipher"})
        )
        _use_rpc(
            monkeypatch,
            _Rpc(rows=[{"name": "Finnhub", "ciphertext": "durable-cipher", "payload": None}]),
        )

        assert registry._load_settings() == {"Finnhub": "durable-cipher"}

    def test_local_file_fallback_when_supabase_disabled(
        self, no_supabase: None, local_registry_file: Path
    ) -> None:
        local_registry_file.mkdir(parents=True, exist_ok=True)
        (local_registry_file / "provider_keys.json").write_text(
            json.dumps({"Finnhub": "local-cipher"})
        )
        assert registry._load_settings() == {"Finnhub": "local-cipher"}

    def test_store_key_writes_remote_first(
        self,
        supabase_trio: None,
        local_registry_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rpc = _Rpc()
        _use_rpc(monkeypatch, rpc)
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())
        monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

        registry._store_api_key("Finnhub", "fh-secret")

        # Remote write happens before anything else (and before the local file).
        assert rpc.fns()[0] == "gw_upsert_provider_key"
        fn, payload = rpc.calls[0]
        assert payload["p_store"] == "market"
        assert payload["p_name"] == "Finnhub"
        assert payload["p_ciphertext"].startswith("gAAAA")  # ciphertext, never plaintext
        assert "fh-secret" not in json.dumps(payload)
        # Local fallback file was written after the remote write succeeded.
        saved = json.loads((local_registry_file / "provider_keys.json").read_text())
        assert registry._read_api_key("Finnhub") == "fh-secret"
        assert saved["Finnhub"] == payload["p_ciphertext"]

        registry._delete_api_key("Finnhub")
        assert rpc.calls[-1][0] == "gw_delete_provider_key"
        assert registry._read_api_key("Finnhub") is None

    def test_failed_remote_write_leaves_local_file_untouched(
        self,
        supabase_trio: None,
        local_registry_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _use_rpc(monkeypatch, _Rpc(fail=True))
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())

        with pytest.raises(RuntimeError, match="unreachable"):
            registry._store_api_key("Finnhub", "fh-secret")

        # "Not saved" must be true: nothing landed locally either.
        assert not (local_registry_file / "provider_keys.json").exists()

    def test_old_local_key_promoted_when_remote_empty(
        self,
        supabase_trio: None,
        local_registry_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Data written before Supabase persistence existed must survive the
        # update: it gets pushed up on first read against an empty store.
        local_registry_file.mkdir(parents=True, exist_ok=True)
        (local_registry_file / "provider_keys.json").write_text(
            json.dumps({"Finnhub": "pre-supabase-cipher"})
        )
        rpc = _Rpc()  # remote: zero rows
        _use_rpc(monkeypatch, rpc)

        assert registry._load_settings() == {"Finnhub": "pre-supabase-cipher"}
        upserts = [c for c in rpc.calls if c[0] == "gw_upsert_provider_key"]
        assert len(upserts) == 1
        assert upserts[0][1]["p_store"] == "market"
        assert upserts[0][1]["p_name"] == "Finnhub"
        assert upserts[0][1]["p_ciphertext"] == "pre-supabase-cipher"

    def test_backfill_runs_once_and_remote_wins_afterwards(
        self,
        supabase_trio: None,
        local_registry_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        local_registry_file.mkdir(parents=True, exist_ok=True)
        (local_registry_file / "provider_keys.json").write_text(
            json.dumps({"Finnhub": "old-cipher"})
        )
        rpc = _Rpc()
        _use_rpc(monkeypatch, rpc)
        registry._load_settings()
        upserts = [c for c in rpc.calls if c[0] == "gw_upsert_provider_key"]
        assert len(upserts) == 1
        assert "market" in key_store._backfilled

        # If the store later reports empty again (rows wiped elsewhere), the
        # per-process guard must not re-push stale local data — deletion wins.
        rpc.rows.clear()
        key_store._cache["market"] = (time.monotonic() - (key_store._TTL + 1), {})
        assert registry._load_settings() == {"Finnhub": "old-cipher"}  # local view
        assert len([c for c in rpc.calls if c[0] == "gw_upsert_provider_key"]) == 1

    def test_failed_promotion_falls_back_to_local_and_stays_eligible(
        self,
        supabase_trio: None,
        local_registry_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        local_registry_file.mkdir(parents=True, exist_ok=True)
        (local_registry_file / "provider_keys.json").write_text(
            json.dumps({"Finnhub": "old-cipher"})
        )
        _use_rpc(monkeypatch, _Rpc(fail_fns={"gw_upsert_provider_key"}))

        # Never raises on a read path, keeps showing the old data, and stays
        # eligible so a later read retries the promotion.
        assert registry._load_settings() == {"Finnhub": "old-cipher"}
        assert "market" not in key_store._backfilled

    def test_backfill_skipped_when_remote_has_rows(
        self,
        supabase_trio: None,
        local_registry_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        local_registry_file.mkdir(parents=True, exist_ok=True)
        (local_registry_file / "provider_keys.json").write_text(
            json.dumps({"Finnhub": "stale-local"})
        )
        rpc = _Rpc(rows=[{"name": "Finnhub", "ciphertext": "durable", "payload": None}])
        _use_rpc(monkeypatch, rpc)

        assert registry._load_settings() == {"Finnhub": "durable"}
        assert not [c for c in rpc.calls if c[0] == "gw_upsert_provider_key"]


class TestLlmProvidersIntegration:
    @pytest.fixture
    def local_llm_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        bundled = tmp_path / "settings"
        monkeypatch.setattr(llm_svc, "_SETTINGS_DIR", bundled)
        monkeypatch.setattr(llm_svc, "_SETTINGS_FILE", bundled / "llm_providers.json")
        return bundled

    def test_store_rebuilt_from_durable_rows(
        self,
        supabase_trio: None,
        local_llm_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        local_llm_file.mkdir(parents=True, exist_ok=True)
        (local_llm_file / "llm_providers.json").write_text(
            json.dumps({"openrouter": {"base_url": "https://stale", "api_key": "stale-c"}})
        )
        _use_rpc(
            monkeypatch,
            _Rpc(
                rows=[
                    {
                        "name": "openrouter",
                        "ciphertext": "gAAAA-durable",
                        "payload": {"base_url": "https://durable", "models": ["m1"]},
                    }
                ],
                store="llm",
            ),
        )

        store = llm_svc._load_store()
        assert store == {
            "openrouter": {
                "base_url": "https://durable",
                "models": ["m1"],
                "api_key": "gAAAA-durable",
            }
        }

    def test_save_pushes_payload_and_ciphertext_remote_first(
        self,
        supabase_trio: None,
        local_llm_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rpc = _Rpc(
            rows=[
                {
                    "name": "openrouter",
                    "ciphertext": "gAAAA-existing",
                    "payload": {"base_url": "https://old"},
                }
            ],
            store="llm",
        )
        _use_rpc(monkeypatch, rpc)
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())

        # base_url-only update: the existing ciphertext must be preserved,
        # api_key itself must never appear in the non-secret payload.
        llm_svc.save_provider_settings("openrouter", base_url="https://new.example/v1")

        upserts = [c for c in rpc.calls if c[0] == "gw_upsert_provider_key"]
        assert upserts, "settings must be pushed to Supabase"
        _, payload = upserts[-1]
        assert payload["p_store"] == "llm"
        assert payload["p_name"] == "openrouter"
        assert payload["p_ciphertext"] == "gAAAA-existing"
        assert payload["p_payload"] == {"base_url": "https://new.example/v1"}
        assert "api_key" not in payload["p_payload"]

    def test_new_api_key_is_encrypted_and_pushed(
        self,
        supabase_trio: None,
        local_llm_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rpc = _Rpc(rows=[])
        _use_rpc(monkeypatch, rpc)
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())

        llm_svc.save_provider_settings("openrouter", api_key="sk-or-plain")

        _, payload = rpc.calls[-1]
        assert payload["p_ciphertext"].startswith("gAAAA")
        assert "sk-or-plain" not in json.dumps(payload)
        # Round trip: reload decrypts the durable ciphertext.
        assert llm_svc.stored_api_key("openrouter") == "sk-or-plain"

    def test_delete_clears_distant_key_but_keeps_payload(
        self,
        supabase_trio: None,
        local_llm_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rpc = _Rpc(
            rows=[
                {
                    "name": "openrouter",
                    "ciphertext": "gAAAA-c",
                    "payload": {"base_url": "https://x"},
                }
            ],
            store="llm",
        )
        _use_rpc(monkeypatch, rpc)

        assert llm_svc.delete_provider_key("openrouter") is True
        fn, payload = rpc.calls[-1]
        assert fn == "gw_upsert_provider_key"  # row kept: payload survives
        assert payload["p_ciphertext"] is None
        assert payload["p_payload"] == {"base_url": "https://x"}

    def test_delete_removes_row_when_nothing_remains(
        self,
        supabase_trio: None,
        local_llm_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rpc = _Rpc(
            rows=[{"name": "ollama-local", "ciphertext": "gAAAA-c", "payload": None}],
            store="llm",
        )
        _use_rpc(monkeypatch, rpc)

        assert llm_svc.delete_provider_key("ollama-local") is True
        assert rpc.calls[-1][0] == "gw_delete_provider_key"

    def test_old_local_llm_settings_promoted_when_remote_empty(
        self,
        supabase_trio: None,
        local_llm_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pre-Supabase LLM config (key + custom base URL + model list) must
        # survive the update: promoted as ciphertext + non-secret payload.
        local_llm_file.mkdir(parents=True, exist_ok=True)
        (local_llm_file / "llm_providers.json").write_text(
            json.dumps(
                {
                    "openrouter": {
                        "base_url": "https://old.example/v1",
                        "api_key": "gAAAA-old",
                        "models": ["m1"],
                        "default_model": "m1",
                    }
                }
            )
        )
        rpc = _Rpc(rows=[], store="llm")  # remote: zero rows
        _use_rpc(monkeypatch, rpc)

        store = llm_svc._load_store()
        assert store == {
            "openrouter": {
                "base_url": "https://old.example/v1",
                "api_key": "gAAAA-old",
                "models": ["m1"],
                "default_model": "m1",
            }
        }
        upserts = [c for c in rpc.calls if c[0] == "gw_upsert_provider_key"]
        assert len(upserts) == 1
        _, payload = upserts[0]
        assert payload["p_store"] == "llm"
        assert payload["p_ciphertext"] == "gAAAA-old"
        assert payload["p_payload"] == {
            "base_url": "https://old.example/v1",
            "models": ["m1"],
            "default_model": "m1",
        }
        assert "api_key" not in payload["p_payload"]


class TestRouteStatusCodes:
    @pytest.mark.asyncio
    async def test_put_llm_provider_503_when_remote_write_fails(
        self,
        supabase_trio: None,
        auth_user,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bundled = tmp_path / "settings"
        monkeypatch.setattr(llm_svc, "_SETTINGS_DIR", bundled)
        monkeypatch.setattr(llm_svc, "_SETTINGS_FILE", bundled / "llm_providers.json")
        _use_rpc(monkeypatch, _Rpc(fail=True))
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())

        response = await fetch(
            "/llm/providers/openrouter", "PUT", {"api_key": "sk-or-x"}
        )
        assert response.status_code == 503
        assert "unreachable" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_put_llm_provider_200_when_remote_write_succeeds(
        self,
        supabase_trio: None,
        auth_user,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bundled = tmp_path / "settings"
        monkeypatch.setattr(llm_svc, "_SETTINGS_DIR", bundled)
        monkeypatch.setattr(llm_svc, "_SETTINGS_FILE", bundled / "llm_providers.json")
        _use_rpc(monkeypatch, _Rpc(rows=[]))
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())

        response = await fetch(
            "/llm/providers/openrouter", "PUT", {"api_key": "sk-or-x"}
        )
        assert response.status_code == 200
        assert response.json() == {"provider": "openrouter", "saved": True}

    @pytest.mark.asyncio
    async def test_settings_key_save_503_when_remote_write_fails(
        self,
        supabase_trio: None,
        auth_user,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _use_rpc(monkeypatch, _Rpc(fail=True))
        monkeypatch.setenv("GATEWAY_PROVIDER_KEY", registry._make_fernet_key().decode())

        response = await fetch(
            "/settings/providers/Finnhub/key", "POST", {"api_key": "fh-x"}
        )
        assert response.status_code == 503
        assert "unreachable" in response.json()["detail"]
