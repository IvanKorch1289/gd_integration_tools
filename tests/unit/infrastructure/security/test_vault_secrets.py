# ruff: noqa: S101
"""Тесты :class:`VaultSecretsBackend` (Wave 1.2 / S3).

Используем мок-клиент hvac (`FakeHvacClient`), чтобы не требовать сетевого
доступа к реальному Vault. Smoke-тест с реальным Vault — в
``tests/integration/test_vault_secrets_smoke.py`` (skip-if-no-VAULT_ADDR).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from src.backend.infrastructure.security.vault_secrets import VaultSecretsBackend


class _FakeKVv2:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store
        self.fail_once_with: BaseException | None = None
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def read_secret_version(self, *, path: str, mount_point: str) -> dict[str, Any]:
        self.calls.append(("read", path, None))
        self._maybe_raise()
        if path not in self._store:
            raise KeyError(path)
        return {"data": {"data": self._store[path], "metadata": {"version": "1"}}}

    def create_or_update_secret(
        self, *, path: str, secret: dict[str, Any], mount_point: str
    ) -> dict[str, Any]:
        self.calls.append(("write", path, secret))
        self._maybe_raise()
        self._store[path] = {**self._store.get(path, {}), **secret}
        return {"ok": True}

    def delete_metadata_and_all_versions(
        self, *, path: str, mount_point: str
    ) -> dict[str, Any]:
        self.calls.append(("delete", path, None))
        self._maybe_raise()
        self._store.pop(path, None)
        return {"ok": True}

    def list_secrets(self, *, path: str, mount_point: str) -> dict[str, Any]:
        self.calls.append(("list", path, None))
        self._maybe_raise()
        keys = [k.split("/", 1)[1] for k in self._store if k.startswith(f"{path}/")]
        return {"data": {"keys": keys}}

    def _maybe_raise(self) -> None:
        if self.fail_once_with is not None:
            exc, self.fail_once_with = self.fail_once_with, None
            raise exc


class _FakeKV:
    """Имитация hvac client.secrets.kv (с .v2)."""

    def __init__(self, kv_v2: _FakeKVv2) -> None:
        self.v2 = kv_v2


class _FakeSecrets:
    def __init__(self, kv: _FakeKV) -> None:
        self.kv = kv


class _FakeClient:
    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self.kv = _FakeKVv2(store)
        self.secrets = _FakeSecrets(_FakeKV(self.kv))
        self.authenticated = True

    def is_authenticated(self) -> bool:
        return self.authenticated


@pytest.fixture()
def fake_client() -> _FakeClient:
    return _FakeClient(
        store={
            "app/db": {"value": "postgres-pass", "user": "app"},
            "app/api": {"value": "api-key-1"},
        }
    )


@pytest.fixture()
def backend(fake_client: _FakeClient) -> VaultSecretsBackend:
    return VaultSecretsBackend(
        addr="http://vault:8200",
        token="fake-token",
        cache_ttl_s=60.0,
        client_factory=lambda: fake_client,
    )


@pytest.mark.asyncio
async def test_get_secret_value_field(
    backend: VaultSecretsBackend, fake_client: _FakeClient
) -> None:
    assert await backend.get_secret("app/db") == "postgres-pass"
    assert fake_client.kv.calls == [("read", "app/db", None)]


@pytest.mark.asyncio
async def test_get_secret_specific_field(backend: VaultSecretsBackend) -> None:
    assert await backend.get_secret("app/db#user") == "app"


@pytest.mark.asyncio
async def test_get_secret_missing_returns_none(backend: VaultSecretsBackend) -> None:
    assert await backend.get_secret("does/not/exist") is None


@pytest.mark.asyncio
async def test_get_secret_uses_cache(
    backend: VaultSecretsBackend, fake_client: _FakeClient
) -> None:
    await backend.get_secret("app/db")
    await backend.get_secret("app/db")
    assert sum(1 for c in fake_client.kv.calls if c[0] == "read") == 1


@pytest.mark.asyncio
async def test_get_secret_cache_ttl_expires(fake_client: _FakeClient) -> None:
    backend = VaultSecretsBackend(
        addr="http://vault:8200",
        token="t",
        cache_ttl_s=0.0,
        client_factory=lambda: fake_client,
    )
    await backend.get_secret("app/db")
    time.sleep(0.01)
    await backend.get_secret("app/db")
    assert sum(1 for c in fake_client.kv.calls if c[0] == "read") == 2


@pytest.mark.asyncio
async def test_set_secret_invalidates_cache(
    backend: VaultSecretsBackend, fake_client: _FakeClient
) -> None:
    await backend.get_secret("app/db")
    await backend.set_secret("app/db", "new-pass")
    assert await backend.get_secret("app/db") == "new-pass"
    assert ("write", "app/db", {"value": "new-pass"}) in fake_client.kv.calls


@pytest.mark.asyncio
async def test_delete_secret(
    backend: VaultSecretsBackend, fake_client: _FakeClient
) -> None:
    assert await backend.delete_secret("app/db") is True
    assert "app/db" not in fake_client.kv._store


@pytest.mark.asyncio
async def test_list_keys(backend: VaultSecretsBackend) -> None:
    keys = await backend.list_keys("app")
    assert sorted(keys) == ["app/api", "app/db"]


@pytest.mark.asyncio
async def test_health_check_ok(backend: VaultSecretsBackend) -> None:
    assert await backend.health_check() is True


@pytest.mark.asyncio
async def test_health_check_failure(fake_client: _FakeClient) -> None:
    fake_client.authenticated = False
    backend = VaultSecretsBackend(
        addr="http://vault:8200", token="t", client_factory=lambda: fake_client
    )
    assert await backend.health_check() is False


@pytest.mark.asyncio
async def test_reauth_on_forbidden() -> None:
    """На Forbidden: одна попытка re-auth (новый клиент) + retry."""
    pytest.importorskip("hvac")
    import hvac.exceptions as hv_exc

    builds: list[_FakeClient] = []
    store: dict[str, dict[str, Any]] = {"app/db": {"value": "ok"}}

    def factory() -> _FakeClient:
        client = _FakeClient(store)
        if not builds:
            client.kv.fail_once_with = hv_exc.Forbidden("denied")
        builds.append(client)
        return client

    backend = VaultSecretsBackend(
        addr="http://vault:8200",
        token="t",
        client_factory=factory,  # type: ignore[arg-type]
    )
    value = await backend.get_secret("app/db")
    assert value == "ok"
    assert len(builds) == 2  # начальный + re-auth
