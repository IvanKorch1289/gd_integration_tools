"""ADR-0401 — ``CacheInvalidator`` покрывает все уровни кэша (L1/L2/L3).

До фикса backend'ы L1 (memory) и L3 (disk) создавались напрямую в
``plugins/composition/service_setup.py`` и в глобальный ``CacheInvalidator``
не регистрировались — регистрировался только primary (Redis), и то
непосредственно в ``infrastructure/cache/factory.py``. В результате
tag/pattern-инвалидация чистила только primary-тир: после отказа Redis
клиент получал stale-значения из memory/disk-fallback.

Тесты покрывают:
* tag-поддержку memory/disk backend'ов (``bind_key_to_tag`` + ``delete_by_tag``);
* регистрацию fallback-уровней в глобальном инвалидаторе;
* сквозную инвалидацию по тегу (L1 + L3 чистятся одной операцией).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.config.services.cache import CacheSettings
from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.cache.factory import create_cache_fallback_backends
from src.backend.infrastructure.cache.invalidator import (
    CacheInvalidator,
    get_cache_invalidator,
    set_cache_invalidator,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated_invalidator() -> None:
    """Изолирует глобальный инвалидатор (иначе тесты делят состояние)."""
    set_cache_invalidator(CacheInvalidator())
    yield
    set_cache_invalidator(CacheInvalidator())


# ── backend-уровень: tag-поддержка ───────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_backend_delete_by_tag_removes_key() -> None:
    """MemoryBackend умеет привязывать ключ к тегу и удалять его по тегу."""
    backend = MemoryBackend(maxsize=10)
    await backend.set("k1", b"v1")
    await backend.bind_key_to_tag("entity:orders", "k1")

    removed = await backend.delete_by_tag("entity:orders")

    assert removed == 1
    assert await backend.get("k1") is None


@pytest.mark.asyncio
async def test_disk_backend_delete_by_tag_removes_key(tmp_path: Path) -> None:
    """DiskCacheBackend умеет привязывать ключ к тегу и удалять его по тегу."""
    backend = DiskCacheBackend(tmp_path / "disk")
    await backend.set("k1", b"v1")
    await backend.bind_key_to_tag("entity:orders", "k1")

    removed = await backend.delete_by_tag("entity:orders")

    assert removed == 1
    assert await backend.get("k1") is None


@pytest.mark.asyncio
async def test_memory_backend_delete_by_pattern_returns_count() -> None:
    """MemoryBackend отдаёт количество удалённых по pattern ключей."""
    backend = MemoryBackend(maxsize=10)
    await backend.set("ns:a", b"1")
    await backend.set("ns:b", b"2")
    await backend.set("other", b"3")

    removed = await backend.delete_by_pattern("ns:*")

    assert removed == 2
    assert await backend.get("ns:a") is None
    assert await backend.get("other") == b"3"


# ── регистрация уровней в глобальном инвалидаторе ────────────────────────


@pytest.mark.asyncio
async def test_fallback_backends_registered_in_invalidator(tmp_path: Path) -> None:
    """Fallback-уровни обязаны попасть в глобальный CacheInvalidator."""
    settings = CacheSettings(
        backend="memory",
        l1_enabled=True,
        l1_maxsize=32,
        disk_fallback_enabled=True,
        disk_fallback_path=str(tmp_path / "disk"),
    )

    memory, disk = create_cache_fallback_backends(settings)

    assert memory is not None
    assert disk is not None
    registered = get_cache_invalidator().backends
    assert memory in registered
    assert disk in registered


@pytest.mark.asyncio
async def test_tag_invalidation_clears_l1_and_l3(tmp_path: Path) -> None:
    """Инвалидация по тегу чистит и memory (L1), и disk (L3)."""
    settings = CacheSettings(
        backend="memory",
        l1_enabled=True,
        l1_maxsize=32,
        disk_fallback_enabled=True,
        disk_fallback_path=str(tmp_path / "disk"),
    )
    memory, disk = create_cache_fallback_backends(settings)
    assert memory is not None and disk is not None

    await memory.set("orders:1", b"payload")
    await disk.set("orders:1", b"payload")
    await memory.bind_key_to_tag("entity:orders", "orders:1")
    await disk.bind_key_to_tag("entity:orders", "orders:1")

    removed = await get_cache_invalidator().invalidate("entity:orders")

    assert removed == 2
    assert await memory.get("orders:1") is None
    assert await disk.get("orders:1") is None


# ── composition root регистрирует все уровни ─────────────────────────────


def test_fallback_tiers_registered_in_invalidator(tmp_path: Path) -> None:
    """L1/L3 обязаны попасть в инвалидатор (ADR-0401, дефект 3).

    Проверяем фабрику напрямую: инвалидатор — глобальный синглтон, поэтому
    состав его реестра зависит от порядка тестов; контракт же — «fallback-тиры
    регистрируются», и он проверяется по идентичности объектов.
    """
    from src.backend.core.config.services.cache import CacheSettings
    from src.backend.infrastructure.cache.factory import create_cache_fallback_backends

    fake_settings = CacheSettings(
        backend="memory",
        l1_enabled=True,
        l1_maxsize=8,
        disk_fallback_enabled=True,
        disk_fallback_path=str(tmp_path / "disk"),
    )

    memory, disk = create_cache_fallback_backends(
        fake_settings,
        disk_path=str(tmp_path / "disk"),
    )

    assert memory is not None, "L1 (memory) не создан"
    assert disk is not None, "L3 (disk) не создан"

    registered = get_cache_invalidator().backends
    assert any(backend is memory for backend in registered), (
        "L1 (memory) не зарегистрирован в инвалидаторе"
    )
    assert any(backend is disk for backend in registered), (
        "L3 (disk) не зарегистрирован в инвалидаторе"
    )
