"""
Тесты CacheInvalidator.

Проверяют:
    * Инвалидация одного тега → удаление соответствующих ключей.
    * Инвалидация нескольких тегов → все ключи удалены за один вызов.
    * Несколько backend'ов — инвалидация идёт во все параллельно.
    * Отсутствие тегов или backend'ов → invalidate возвращает 0.
    * Backend может бросить исключение — остальные продолжают работу.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.cache.invalidator import (
    CacheInvalidator,
    InMemoryCacheBackend,
)


class _FailingBackend:
    """Backend, падающий при ``delete_by_tag`` — для проверки resilience."""

    async def delete_by_tag(self, tag: str) -> int:
        raise RuntimeError("backend unavailable")


async def test_invalidate_single_tag_removes_keys() -> None:
    """После invalidate кэш-ключи, привязанные к тегу, удалены."""
    backend = InMemoryCacheBackend()
    backend.bind_key_to_tag("entity:orders", "orders:list:page=1")
    backend.bind_key_to_tag("entity:orders", "orders:list:page=2")

    invalidator = CacheInvalidator([backend])
    removed = await invalidator.invalidate("entity:orders")

    assert removed == 2
    # Повторный invalidate — уже 0.
    assert await invalidator.invalidate("entity:orders") == 0


async def test_invalidate_multiple_tags() -> None:
    """Одним вызовом удаляются ключи нескольких тегов."""
    backend = InMemoryCacheBackend()
    backend.bind_key_to_tag("entity:orders", "orders:list")
    backend.bind_key_to_tag("entity:orders:42", "orders:get:42")
    backend.bind_key_to_tag("entity:users", "users:list")

    invalidator = CacheInvalidator([backend])
    removed = await invalidator.invalidate(
        "entity:orders", "entity:orders:42", "entity:users"
    )

    assert removed == 3


async def test_invalidate_fans_out_across_backends() -> None:
    """Все backend'ы получают команду на удаление."""
    b1 = InMemoryCacheBackend()
    b2 = InMemoryCacheBackend()
    b1.bind_key_to_tag("entity:orders", "redis_key")
    b2.bind_key_to_tag("entity:orders", "disk_key")

    invalidator = CacheInvalidator([b1, b2])
    removed = await invalidator.invalidate("entity:orders")

    assert removed == 2  # 1 ключ в каждом backend


async def test_empty_tags_noop() -> None:
    """Без тегов invalidate ничего не делает и возвращает 0."""
    backend = InMemoryCacheBackend()
    invalidator = CacheInvalidator([backend])
    assert await invalidator.invalidate() == 0


async def test_no_backends_noop() -> None:
    """Без backend'ов invalidate возвращает 0."""
    invalidator = CacheInvalidator([])
    assert await invalidator.invalidate("entity:orders") == 0


async def test_failing_backend_does_not_break_others() -> None:
    """Ошибка одного backend'а не мешает другим."""
    good = InMemoryCacheBackend()
    good.bind_key_to_tag("entity:orders", "key1")
    failing = _FailingBackend()

    invalidator = CacheInvalidator([failing, good])
    removed = await invalidator.invalidate("entity:orders")

    assert removed == 1  # только good отработал
