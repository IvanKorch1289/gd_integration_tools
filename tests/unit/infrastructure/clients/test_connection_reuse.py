"""Smoke-тесты для ConnectionReuseManager.

Проверяет базовое поведение:
- пропуск проверок при выключенном flag;
- возврат connection при нормальных условиях;
- вызов ping при idle > idle_timeout;
- auto-recycle connection при lifetime > max_lifetime;
- singleton-паттерн get_connection_reuse_manager().
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Вспомогательный контекст-менеджер для управления флагом
# ---------------------------------------------------------------------------


def _patch_flag(value: bool):
    """Патчит feature-flag connection_reuse_manager в тестируемом модуле."""
    return patch(
        "src.backend.infrastructure.clients.connection_reuse._is_flag_enabled",
        return_value=value,
    )


# ---------------------------------------------------------------------------
# Тест 1: flag OFF — acquire возвращает pool без проверок
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_when_flag_off() -> None:
    """При выключенном feature-flag acquire() возвращает pool-объект мгновенно.

    Ни ping_callable, ни какая-либо проверка lifetime не должна вызываться.
    """
    from src.backend.infrastructure.clients.connection_reuse import (
        ConnectionReuseManager,
    )

    ping = AsyncMock()
    fake_pool = object()

    manager = ConnectionReuseManager()
    manager.register_pool(
        name="test_pool",
        pool=fake_pool,
        ping_callable=ping,
        max_lifetime_seconds=3600.0,
        idle_timeout_seconds=60.0,
    )

    with _patch_flag(False):
        result = await manager.acquire("test_pool")

    assert result is fake_pool
    ping.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 2: acquire при flag ON возвращает connection из pool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_returns_pool_connection() -> None:
    """При включённом flag acquire() возвращает pool-объект при свежем connection.

    Условие: connection только что создан (lifetime < max_lifetime,
    idle < idle_timeout) — ping не вызывается.
    """
    from src.backend.infrastructure.clients.connection_reuse import (
        ConnectionReuseManager,
    )

    ping = AsyncMock()
    fake_pool = object()

    manager = ConnectionReuseManager()
    manager.register_pool(
        name="fresh_pool",
        pool=fake_pool,
        ping_callable=ping,
        max_lifetime_seconds=3600.0,
        idle_timeout_seconds=60.0,
    )

    with _patch_flag(True):
        # Первый acquire — создаёт метаданные
        result = await manager.acquire("fresh_pool")

    assert result is fake_pool
    # ping не вызывается: connection свежий, idle = 0
    ping.assert_not_called()


# ---------------------------------------------------------------------------
# Тест 3: ping вызывается при idle > idle_timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pings_idle_connection() -> None:
    """При idle-периоде превышающем idle_timeout_seconds вызывается ping_callable.

    Имитируем устаревший last_used путём прямой манипуляции метаданными.
    """
    from src.backend.infrastructure.clients.connection_reuse import (
        ConnectionMetadata,
        ConnectionReuseManager,
    )

    ping = AsyncMock()
    fake_pool = object()

    manager = ConnectionReuseManager()
    manager.register_pool(
        name="idle_pool",
        pool=fake_pool,
        ping_callable=ping,
        max_lifetime_seconds=3600.0,
        idle_timeout_seconds=60.0,
    )

    # Устанавливаем метаданные с устаревшим last_used (120 секунд назад)
    now = time.monotonic()
    manager._pools["idle_pool"].metadata = ConnectionMetadata(
        name="idle_pool",
        created_at=now - 30.0,  # lifetime 30s < max_lifetime 3600s
        last_used=now - 120.0,  # idle 120s > idle_timeout 60s
    )
    manager._pools["idle_pool"].last_connection = fake_pool

    with _patch_flag(True):
        result = await manager.acquire("idle_pool")

    assert result is fake_pool
    # ping должен быть вызван один раз с pool-объектом
    ping.assert_awaited_once_with(fake_pool)


# ---------------------------------------------------------------------------
# Тест 4: auto-recycle при lifetime > max_lifetime
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recycles_old_connection_after_max_lifetime() -> None:
    """Connection старше max_lifetime_seconds пересоздаётся (auto-recycle).

    После recycle ping_callable вызывается для проверки нового connection.
    Метаданные сбрасываются: created_at обновляется, use_count = 0.
    """
    from src.backend.infrastructure.clients.connection_reuse import (
        ConnectionMetadata,
        ConnectionReuseManager,
    )

    ping = AsyncMock()
    fake_pool = object()

    manager = ConnectionReuseManager()
    manager.register_pool(
        name="old_pool",
        pool=fake_pool,
        ping_callable=ping,
        max_lifetime_seconds=3600.0,
        idle_timeout_seconds=60.0,
    )

    # Устанавливаем метаданные с устаревшим created_at (4 часа назад)
    now = time.monotonic()
    old_created_at = now - 14400.0  # 4 часа > max_lifetime 3600s
    manager._pools["old_pool"].metadata = ConnectionMetadata(
        name="old_pool",
        created_at=old_created_at,
        last_used=now - 5.0,  # недавно использовался
        use_count=42,
    )
    manager._pools["old_pool"].last_connection = fake_pool

    with _patch_flag(True):
        result = await manager.acquire("old_pool")

    assert result is fake_pool

    # ping вызывается после auto-recycle
    ping.assert_awaited_once_with(fake_pool)

    # Метаданные сброшены: created_at обновлён, use_count сдвинулся
    meta = manager._pools["old_pool"].metadata
    assert meta is not None
    assert meta.created_at > old_created_at  # время обновлено
    assert meta.use_count == 1  # ровно один acquire после recycle


# ---------------------------------------------------------------------------
# Тест 5: singleton get_connection_reuse_manager
# ---------------------------------------------------------------------------


def test_singleton() -> None:
    """get_connection_reuse_manager() возвращает один и тот же объект.

    Проверяем identity (is), а не равенство (==).
    """
    import src.backend.infrastructure.clients.connection_reuse as module

    # Сбрасываем singleton перед тестом
    original = module._manager_instance
    module._manager_instance = None

    try:
        from src.backend.infrastructure.clients.connection_reuse import (
            get_connection_reuse_manager,
        )

        instance_a = get_connection_reuse_manager()
        instance_b = get_connection_reuse_manager()
        assert instance_a is instance_b
    finally:
        # Восстанавливаем исходное состояние
        module._manager_instance = original
