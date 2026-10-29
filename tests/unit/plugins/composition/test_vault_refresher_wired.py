"""A2 (ADR-0385): ``VaultSecretRefresher`` должен стартовать в lifespan.

Дефект
------
Инстанс рефрешера создавался в ``plugins/composition/di.py``, но
``start()`` никогда не вызывался — фоновое обновление секретов из Vault
не работало: ротация паролей/токенов не подхватывалась до рестарта.

Ожидание
--------
* операция ``start_vault_secret_refresher`` есть в startup-списках;
* операция ``stop_vault_secret_refresher`` есть в shutdown-списках;
* ``start()``/``stop()`` реально вызываются (проверяется моком).
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.plugins.composition.setup_infra import lifecycle

_REFRESHER_PATH = "src.backend.infrastructure.application.vault_refresher"


class TestVaultRefresherWired:
    """Рефрешер подключён к lifecycle инфраструктуры."""

    def test_start_registered_in_starting_operations(self) -> None:
        """Старт рефрешера есть в legacy-списке startup."""
        names = [name for name, *_ in lifecycle.starting_operations]
        assert "start_vault_secret_refresher" in names

    def test_stop_registered_in_ending_operations(self) -> None:
        """Остановка рефрешера есть в legacy-списке shutdown."""
        names = [name for name, *_ in lifecycle.ending_operations]
        assert "stop_vault_secret_refresher" in names

    def test_typed_operations_have_start_and_stop(self) -> None:
        """Типизированная операция lifecycle содержит пару start/stop."""
        operations = {
            op.name: op for op in lifecycle._build_infrastructure_operations()
        }
        operation = operations.get("start_vault_secret_refresher")
        assert operation is not None, "операция start_vault_secret_refresher нет"
        assert operation.stop is not None, "у операции нет stop-функции"

    def test_functions_are_async(self) -> None:
        """Start/stop — async-функции."""
        assert inspect.iscoroutinefunction(lifecycle._start_vault_secret_refresher)
        assert inspect.iscoroutinefunction(lifecycle._stop_vault_secret_refresher)

    @pytest.mark.asyncio
    async def test_start_invokes_refresher_start(self) -> None:
        """Стартовая функция вызывает ``start()`` рефрешера."""
        refresher = AsyncMock()
        with patch(f"{_REFRESHER_PATH}.get_vault_refresher", return_value=refresher):
            await lifecycle._start_vault_secret_refresher()
        refresher.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_invokes_refresher_stop(self) -> None:
        """Shutdown-функция вызывает ``stop()`` рефрешера."""
        refresher = AsyncMock()
        with patch(f"{_REFRESHER_PATH}.get_vault_refresher", return_value=refresher):
            await lifecycle._stop_vault_secret_refresher()
        refresher.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_failure_does_not_break_lifecycle(self) -> None:
        """Ошибка старта рефрешера не роняет startup приложения."""
        refresher = AsyncMock()
        refresher.start.side_effect = RuntimeError("vault down")
        with patch(f"{_REFRESHER_PATH}.get_vault_refresher", return_value=refresher):
            await lifecycle._start_vault_secret_refresher()
