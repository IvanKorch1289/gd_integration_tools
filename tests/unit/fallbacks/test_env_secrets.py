"""Тесты ``EnvSecretsBackend`` (Wave 21.3c)."""

from __future__ import annotations

import pytest

from src.backend.infrastructure.security.env_secrets import EnvSecretsBackend


@pytest.mark.asyncio
async def test_get_returns_environment_variable(monkeypatch):
    monkeypatch.setenv("GD_TEST_SECRET", "value-from-env")
    backend = EnvSecretsBackend()
    assert await backend.get_secret("GD_TEST_SECRET") == "value-from-env"


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_key():
    backend = EnvSecretsBackend()
    assert await backend.get_secret("__definitely_missing__") is None


@pytest.mark.asyncio
async def test_set_then_get(monkeypatch):
    monkeypatch.delenv("GD_NEW_SECRET", raising=False)
    backend = EnvSecretsBackend()
    await backend.set_secret("GD_NEW_SECRET", "new-value")
    assert await backend.get_secret("GD_NEW_SECRET") == "new-value"


@pytest.mark.asyncio
async def test_delete_returns_true_when_existed(monkeypatch):
    monkeypatch.setenv("GD_DEL_SECRET", "to-delete")
    backend = EnvSecretsBackend()
    assert await backend.delete_secret("GD_DEL_SECRET") is True
    assert await backend.get_secret("GD_DEL_SECRET") is None


@pytest.mark.asyncio
async def test_delete_returns_false_when_missing(monkeypatch):
    monkeypatch.delenv("GD_NOT_THERE", raising=False)
    backend = EnvSecretsBackend()
    assert await backend.delete_secret("GD_NOT_THERE") is False


@pytest.mark.asyncio
async def test_list_keys_filters_by_prefix(monkeypatch):
    monkeypatch.setenv("GD_PREFIX_A", "1")
    monkeypatch.setenv("GD_PREFIX_B", "2")
    backend = EnvSecretsBackend()
    keys = await backend.list_keys(prefix="GD_PREFIX_")
    assert "GD_PREFIX_A" in keys
    assert "GD_PREFIX_B" in keys


@pytest.mark.asyncio
async def test_persistence_round_trip(tmp_path):
    path = tmp_path / "secrets.json"
    backend1 = EnvSecretsBackend(persistence_path=path)
    await backend1.set_secret("PERSISTED_KEY", "persisted-value")
    # Новый экземпляр читает файл при инициализации.
    backend2 = EnvSecretsBackend(persistence_path=path)
    assert await backend2.get_secret("PERSISTED_KEY") == "persisted-value"
