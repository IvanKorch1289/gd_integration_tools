"""Тесты :class:`VaultBackend` (V15 S1+S3).

Используем dependency-injected fake hvac.Client, чтобы не поднимать
реальный Vault.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.infrastructure.secrets.vault_backend import VaultBackend, VaultConfig


class _FakeKVv2:
    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self._data = data

    def read_secret_version(
        self, *, path: str, mount_point: str = "secret", version: int | None = None
    ) -> dict[str, Any]:
        if path not in self._data:
            raise KeyError(path)
        snap = self._data[path]
        return {
            "data": {
                "data": snap["data"],
                "metadata": {"version": version or snap.get("version", 1)},
            }
        }

    def read_secret_metadata(
        self, *, path: str, mount_point: str = "secret"
    ) -> dict[str, Any]:
        return {"data": {"current_version": self._data[path].get("version", 1)}}


class _FakeKVAPI:
    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self.v2 = _FakeKVv2(data)


class _FakeSecretsAPI:
    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self.kv = _FakeKVAPI(data)


class _FakeClient:
    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self.secrets = _FakeSecretsAPI(data)


@pytest.fixture()
def fake_client() -> _FakeClient:
    return _FakeClient(
        {
            "db/pg": {"data": {"value": "pg_password"}, "version": 3},
            "api/key": {"data": {"value": "k1"}, "version": 1},
            "json/secret": {"data": {"foo": "bar", "n": 42}, "version": 1},
        }
    )


def test_get_returns_value_field(fake_client: _FakeClient) -> None:
    backend = VaultBackend(config=VaultConfig(url="http://x"), client=fake_client)
    snap = backend.get("db/pg")
    assert snap.value == "pg_password"
    assert snap.version == 3


def test_get_serializes_dict_when_no_value_field(fake_client: _FakeClient) -> None:
    backend = VaultBackend(config=VaultConfig(url="http://x"), client=fake_client)
    snap = backend.get("json/secret")
    # JSON sort_keys=True гарантирует детерминизм.
    assert snap.value == '{"foo": "bar", "n": 42}'


@pytest.mark.asyncio
async def test_get_versioned_passes_version(fake_client: _FakeClient) -> None:
    backend = VaultBackend(config=VaultConfig(url="http://x"), client=fake_client)
    snap = await backend.get_versioned("api/key", 7)
    # _FakeKVv2 echoes version → проверяем, что параметр пробрасывается.
    assert snap.version == 7


@pytest.mark.asyncio
async def test_get_metadata_returns_data_block(fake_client: _FakeClient) -> None:
    backend = VaultBackend(config=VaultConfig(url="http://x"), client=fake_client)
    meta = await backend.get_metadata("db/pg")
    assert meta == {"current_version": 3}
