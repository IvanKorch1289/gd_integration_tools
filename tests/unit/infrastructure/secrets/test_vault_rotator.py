"""Smoke-тесты для VaultSecretRotator.

Проверяют:
    - пропуск запуска при выключенном feature-flag;
    - регистрацию path + callback;
    - вызов callback при изменении metadata.version (mock hvac);
    - идемпотентность singleton get_vault_rotator().
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.secrets.vault_rotator import (
    VaultSecretRotator,
    get_vault_rotator,
)


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные фикстуры
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def rotator() -> VaultSecretRotator:
    """Свежий экземпляр ротатора для каждого теста (не singleton)."""
    return VaultSecretRotator()


def _make_hvac_response(version: int, data: dict[str, Any]) -> dict[str, Any]:
    """Формирует фиктивный ответ hvac KV v2 read_secret_version."""
    return {
        "data": {
            "metadata": {"version": version},
            "data": data,
        }
    }


# ──────────────────────────────────────────────────────────────────────────────
# Тесты
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio()
async def test_rotator_skips_when_flag_off(rotator: VaultSecretRotator) -> None:
    """Ротатор не запускает фоновую задачу при vault_rotation_enabled=False."""
    with patch(
        "src.backend.infrastructure.secrets.vault_rotator.feature_flags",
    ) as mock_flags:
        mock_flags.vault_rotation_enabled = False

        await rotator.start(interval_seconds=1.0)

        # Задача не должна быть создана
        assert rotator._task is None


def test_rotator_registers_path_and_callback(rotator: VaultSecretRotator) -> None:
    """register() добавляет запись в _entries и инициализирует версию как None."""
    callback = MagicMock()
    rotator.register("secret/data/db/password", callback)

    assert len(rotator._entries) == 1
    registered_path, registered_cb = rotator._entries[0]
    assert registered_path == "secret/data/db/password"
    assert registered_cb is callback
    assert rotator._versions["secret/data/db/password"] is None


@pytest.mark.asyncio()
async def test_rotator_tick_calls_callback_on_version_change(
    rotator: VaultSecretRotator,
) -> None:
    """tick() вызывает callback при изменении metadata.version в ответе Vault."""
    path = "secret/data/api/key"
    received: list[dict[str, Any]] = []
    rotator.register(path, received.append)

    # Первый tick: версия 1, кэш пуст → callback вызывается
    mock_hvac_client = MagicMock()
    mock_hvac_client.secrets.kv.v2.read_secret_version.return_value = (
        _make_hvac_response(version=1, data={"api_key": "secret-v1"})
    )

    with patch("hvac.Client", return_value=mock_hvac_client):
        await rotator.tick()

    assert len(received) == 1
    assert received[0] == {"api_key": "secret-v1"}
    assert rotator._versions[path] == 1

    # Второй tick: версия та же (1) → callback НЕ вызывается
    with patch("hvac.Client", return_value=mock_hvac_client):
        await rotator.tick()

    assert len(received) == 1  # без изменений

    # Третий tick: версия 2 → callback вызывается снова
    mock_hvac_client.secrets.kv.v2.read_secret_version.return_value = (
        _make_hvac_response(version=2, data={"api_key": "secret-v2"})
    )

    with patch("hvac.Client", return_value=mock_hvac_client):
        await rotator.tick()

    assert len(received) == 2
    assert received[1] == {"api_key": "secret-v2"}
    assert rotator._versions[path] == 2


def test_rotator_singleton_idempotent() -> None:
    """get_vault_rotator() всегда возвращает один и тот же объект."""
    import src.backend.infrastructure.secrets.vault_rotator as _mod

    # Сбрасываем singleton между тестами
    _mod._vault_rotator_instance = None

    first = get_vault_rotator()
    second = get_vault_rotator()

    assert first is second
    assert isinstance(first, VaultSecretRotator)
