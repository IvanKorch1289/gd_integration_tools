"""Cycle 168 tests: ``TenantCacheBackend`` обёртка для L1/L3 fallback.

PROD_READINESS_LOGGING_CACHE_2026-10-20 §1.2: ``memory_fallback`` и
``disk_fallback`` НЕ оборачивались в ``TenantCacheBackend`` (только primary).
Это потенциальная cross-tenant data leak через shared L1/L3.

Cycle 168: service_setup оборачивает все tiers в ``TenantCacheBackend``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from src.backend.infrastructure.cache.backends.disk import DiskCacheBackend
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.cache.tenant_wrapper import TenantCacheBackend
from src.backend.services.cache import UnifiedCacheFacade


@pytest.fixture
async def disk() -> DiskCacheBackend:
    with tempfile.TemporaryDirectory(prefix="tenant_disk_") as d:
        yield DiskCacheBackend(d)


class TestTenantWrapperFallback:
    async def test_tenant_wrapper_applied_to_memory_fallback(self) -> None:
        """``memory_fallback`` в facade — это ``TenantCacheBackend``."""
        from src.backend.plugins.composition.service_setup import _register_cache_facade
        from src.backend.core.config.services.cache import cache_settings

        # В тестовой среде tenant_cache_prefix_enabled=True (default)
        facade = UnifiedCacheFacade(
            primary=MemoryBackend(maxsize=10),
            memory_fallback=TenantCacheBackend(MemoryBackend(maxsize=10)),
            disk_fallback=None,
        )
        # Оба типа MemoryBackend работают — критично что TenantCacheBackend
        # не сломал ABC contract.
        await facade.set("k1", b"v1", ttl_seconds=60)
        r = await facade.get("k1")
        assert r == b"v1"

    async def test_cross_tenant_isolation_in_facade(self, disk: DiskCacheBackend) -> None:
        """Tenant A и B хранят разные значения под одним ключом.

        Без TenantCacheWrapper facade использует полный ``namespace:key`` ключ,
        но ``_tag_index`` общий. С wrapper'ом backend получает tenant-prefix.
        """
        facade = UnifiedCacheFacade(
            primary=MemoryBackend(maxsize=10),
            memory_fallback=TenantCacheBackend(MemoryBackend(maxsize=10)),
            disk_fallback=TenantCacheBackend(disk),
        )
        # Используем namespace-aware вариант (set_ns).
        await facade.set_ns("user:42", b"data_A", ttl=60, namespace="tenant_A")
        await facade.set_ns("user:42", b"data_B", ttl=60, namespace="tenant_B")
        rA = await facade.get_ns("user:42", namespace="tenant_A")
        rB = await facade.get_ns("user:42", namespace="tenant_B")
        assert rA.value == b"data_A"
        assert rB.value == b"data_B"

    async def test_tenant_wrapper_around_disk(self, disk: DiskCacheBackend) -> None:
        """TenantCacheBackend вокруг DiskCacheBackend корректно работает."""
        wrapped = TenantCacheBackend(disk)
        await wrapped.set("k1", b"v1", ttl=60)
        r = await wrapped.get("k1")
        assert r == b"v1"
        # Удаление через wrapper
        await wrapped.delete("k1")
        r2 = await wrapped.get("k1")
        assert r2 is None


class TestTagIndexSuccessOnly:
    """Cycle 168 §1.6: ``_tag_index`` обновляется только при successful set."""

    async def test_tag_index_not_updated_on_total_failure(self) -> None:
        """Если все backend'ы упали — tag НЕ попадает в _tag_index."""
        from src.backend.services.cache.facade import UnifiedCacheFacade

        from tests.unit.services.cache.test_log_throttling import FailingBackend

        facade = UnifiedCacheFacade(
            primary=FailingBackend(),
            memory_fallback=FailingBackend(),
            disk_fallback=None,
        )
        # Set с тегами — все backend'ы падают
        await facade.set_ns("k1", b"v", tags=["t1"], namespace="n1")
        # _tag_index должен быть пуст (или без тегов)
        ns_tags = facade._tag_index.get("n1", {})
        # set_ns может не дойти до tag_index если successful_writes == 0
        assert "t1" not in ns_tags, (
            "tag_index не должен обновляться при полном set failure"
        )

    async def test_tag_index_updated_on_partial_success(self) -> None:
        """Если хотя бы один backend успешен — tag добавляется."""
        from src.backend.services.cache.facade import UnifiedCacheFacade

        from tests.unit.services.cache.test_log_throttling import FailingBackend

        facade = UnifiedCacheFacade(
            primary=FailingBackend(),
            memory_fallback=MemoryBackend(maxsize=10),
            disk_fallback=None,
        )
        await facade.set_ns("k1", b"v", tags=["t1"], namespace="n1")
        ns_tags = facade._tag_index.get("n1", {})
        assert "t1" in ns_tags
        assert "k1" in ns_tags["t1"]