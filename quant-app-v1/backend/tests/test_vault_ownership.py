"""The secrets vault is owner-scoped per request (NFR-6/NFR-14).

Signed-out calls are 401 from the route dependency. A secret is stored under the
authenticated principal, never an id from the body, and another account sees the
same 404 as a missing name. Entries written before ownership existed have no
owner and stay quarantined rather than becoming visible to the first account.
"""

from __future__ import annotations

import json
import typing

import httpx
import pytest
from fastapi.routing import APIRoute

from app import auth
from app.api.main import app
from app.api.v1 import vault as vault_api
from app.services import secrets_vault


@pytest.fixture(autouse=True)
def isolated_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets_vault, "_SETTINGS_DIR", tmp_path)
    monkeypatch.setattr(secrets_vault, "_VAULT_FILE", tmp_path / "secrets.vault")
    monkeypatch.setattr(secrets_vault, "_VAULT_KEY_FILE", tmp_path / "secrets.vault.key")
    monkeypatch.setenv("GATEWAY_PROVIDER_KEY", "")
    monkeypatch.setenv("GATEWAY_PROVIDER_KEY_FILE", "")
    return tmp_path


def _token(user_id: str) -> str:
    return auth.create_access_token({"sub": user_id, "email": f"{user_id}@example.test"})


async def _request(
    path: str,
    *,
    token: str | None = None,
    method: str = "GET",
    body: dict | None = None,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, headers=headers, json=body)


@pytest.mark.asyncio
async def test_signed_out_vault_routes_answer_401_from_the_dependency() -> None:
    calls = [
        ("/vault", "GET", None),
        ("/vault/alpha", "PUT", {"value": "secret"}),
        ("/vault/alpha/reveal", "GET", None),
        ("/vault/alpha", "DELETE", None),
    ]
    for path, method, body in calls:
        response = await _request(path, method=method, body=body)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_each_owner_sees_only_their_own_secrets(isolated_vault) -> None:
    alice = _token("alice")
    bob = _token("bob")

    saved = await _request(
        "/vault/api-key", token=alice, method="PUT", body={"value": "alice-secret", "note": "A"}
    )
    assert saved.status_code == 200
    assert saved.json()["name"] == "api-key"
    assert "value" not in saved.json()

    alice_list = await _request("/vault", token=alice)
    bob_list = await _request("/vault", token=bob)
    assert [item["name"] for item in alice_list.json()] == ["api-key"]
    assert bob_list.json() == []

    alice_reveal = await _request("/vault/api-key/reveal", token=alice)
    assert alice_reveal.status_code == 200
    assert alice_reveal.json() == {"name": "api-key", "value": "alice-secret"}

    # The foreign name and a truly missing name are indistinguishable.
    bob_reveal = await _request("/vault/api-key/reveal", token=bob)
    bob_missing = await _request("/vault/missing/reveal", token=bob)
    assert bob_reveal.status_code == bob_missing.status_code == 404
    assert bob_reveal.json() == bob_missing.json() == {"detail": "Secret not found"}

    bob_delete = await _request("/vault/api-key", token=bob, method="DELETE")
    bob_delete_missing = await _request("/vault/missing", token=bob, method="DELETE")
    assert bob_delete.status_code == bob_delete_missing.status_code == 404
    assert bob_delete.json() == bob_delete_missing.json() == {"detail": "Secret not found"}

    # Bob's failed delete left Alice's value intact.
    assert (await _request("/vault/api-key/reveal", token=alice)).json()["value"] == "alice-secret"

    deleted = await _request("/vault/api-key", token=alice, method="DELETE")
    assert deleted.status_code == 204
    assert (await _request("/vault/api-key/reveal", token=alice)).status_code == 404


@pytest.mark.asyncio
async def test_ownership_is_taken_from_the_principal_not_the_body(isolated_vault) -> None:
    alice = _token("alice")
    response = await _request(
        "/vault/shared",
        token=alice,
        method="PUT",
        body={"value": "alice-value", "note": "A", "owner_id": "bob", "user_id": "bob"},
    )
    assert response.status_code == 200

    assert (await _request("/vault", token=_token("bob"))).json() == []
    assert (await _request("/vault/shared/reveal", token=_token("bob"))).status_code == 404

    data = json.loads((isolated_vault / "secrets.vault").read_text(encoding="utf-8"))
    entry = next(item for item in data["secrets"].values() if item.get("name") == "shared")
    assert entry["owner_id"] == "alice"
    assert "alice-value" not in json.dumps(data)


@pytest.mark.asyncio
async def test_two_owners_can_use_the_same_secret_name(isolated_vault) -> None:
    alice = _token("alice")
    bob = _token("bob")
    await _request("/vault/shared", token=alice, method="PUT", body={"value": "alice-value"})
    await _request("/vault/shared", token=bob, method="PUT", body={"value": "bob-value"})

    assert (await _request("/vault/shared/reveal", token=alice)).json()["value"] == "alice-value"
    assert (await _request("/vault/shared/reveal", token=bob)).json()["value"] == "bob-value"

    assert (await _request("/vault/shared", token=alice, method="DELETE")).status_code == 204
    assert (await _request("/vault/shared/reveal", token=alice)).status_code == 404
    assert (await _request("/vault/shared/reveal", token=bob)).json()["value"] == "bob-value"


def test_legacy_ownerless_entries_stay_invisible_and_are_not_deleted(isolated_vault) -> None:
    legacy = {
        "version": 1,
        "secrets": {
            "legacy-key": {
                "cipher": "not-a-real-cipher",
                "length": 9,
                "note": "pre-ownership",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
        },
    }
    (isolated_vault / "secrets.vault").write_text(json.dumps(legacy), encoding="utf-8")

    assert secrets_vault.list_secrets("alice") == []
    assert secrets_vault.get_secret("alice", "legacy-key") is None
    assert secrets_vault.delete_secret("alice", "legacy-key") is False

    secrets_vault.set_secret("alice", "fresh-key", "fresh-value")
    assert [item["name"] for item in secrets_vault.list_secrets("alice")] == ["fresh-key"]

    data = json.loads((isolated_vault / "secrets.vault").read_text(encoding="utf-8"))
    assert "legacy-key" in data["secrets"]
    assert "owner_id" not in data["secrets"]["legacy-key"]
    assert "fresh-value" not in json.dumps(data)


def test_empty_owner_is_rejected(isolated_vault) -> None:
    with pytest.raises(secrets_vault.VaultError):
        secrets_vault.list_secrets("")
    with pytest.raises(secrets_vault.VaultError):
        secrets_vault.set_secret("", "name", "value")


def test_every_vault_route_requires_a_principal() -> None:
    routes = [route for route in vault_api.router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 4
    for route in routes:
        hints = typing.get_type_hints(route.endpoint, include_extras=True)
        assert "user" in hints, route.path
