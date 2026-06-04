"""Sprint 21 W2 — TenantCacheBackend isolation tests.

Источник: PLAN.md V22.2 §4 + B-03 cache poisoning closure.

Покрытие:
    * cross-tenant isolation — tenant A не видит ключи tenant B при get.
    * pattern delete не пересекает tenant boundaries.
    * unscoped fallback изолирован от tenant-scoped namespace.
    * feature-flag OFF → wrapper делегирует напрямую (no-op).
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Callable

import pytest

from src.backend.core.tenancy import TenantContext, tenant_scope
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.cache.tenant_wrapper import (
    DEFAULT_UNSCOPED_PREFIX,
    TenantCacheBackend,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _enable_tenant_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает feature-flag tenant_cache_prefix_enabled на время теста."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(
        features_module.feature_flags,
        "tenant_cache_prefix_enabled",
        True,
        raising=False,
    )


@pytest.fixture
def backend() -> TenantCacheBackend:
    return TenantCacheBackend(MemoryBackend(maxsize=128, default_ttl=60))


async def test_set_and_get_within_same_tenant(backend: TenantCacheBackend) -> None:
    """Same-tenant get возвращает записанный value."""
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await backend.set("orders:123", b"payload-a")
        result = await backend.get("orders:123")
        assert result == b"payload-a"


async def test_cross_tenant_isolation(backend: TenantCacheBackend) -> None:
    """Tenant B не видит keys tenant A — даже с одинаковым raw-ключом."""
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await backend.set("orders:123", b"payload-a")

    with tenant_scope(TenantContext(tenant_id="bank_b")):
        leak = await backend.get("orders:123")
        assert leak is None, f"tenant B видит данные tenant A: {leak!r}"
        await backend.set("orders:123", b"payload-b")

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        own = await backend.get("orders:123")
        assert own == b"payload-a", "tenant A потерял свой ключ после write tenant B"


async def test_delete_pattern_within_tenant(backend: TenantCacheBackend) -> None:
    """delete_pattern удаляет только tenant-scoped ключи."""
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await backend.set("orders:1", b"a-1")
        await backend.set("orders:2", b"a-2")

    with tenant_scope(TenantContext(tenant_id="bank_b")):
        await backend.set("orders:1", b"b-1")
        await backend.delete_pattern("orders:*")

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        # tenant A должен сохранить свои ключи
        assert await backend.get("orders:1") == b"a-1"
        assert await backend.get("orders:2") == b"a-2"

    with tenant_scope(TenantContext(tenant_id="bank_b")):
        assert await backend.get("orders:1") is None


async def test_unscoped_fallback_isolated(backend: TenantCacheBackend) -> None:
    """При отсутствии tenant — keys пишутся в _unscoped_ namespace."""
    # Без tenant_scope
    await backend.set("global:key", b"unscoped")
    result = await backend.get("global:key")
    assert result == b"unscoped"

    # Tenant scope не видит unscoped
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        leak = await backend.get("global:key")
        assert leak is None

    # Underlying storage содержит prefixed key
    wrapped = backend.wrapped
    assert isinstance(wrapped, MemoryBackend)
    assert DEFAULT_UNSCOPED_PREFIX + "global:key" in wrapped._cache


async def test_exists_respects_tenant(backend: TenantCacheBackend) -> None:
    """exists() сравнивает scoped ключ."""
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await backend.set("flag", b"1")
        assert await backend.exists("flag") is True

    with tenant_scope(TenantContext(tenant_id="bank_b")):
        assert await backend.exists("flag") is False


async def test_delete_multiple_keys(backend: TenantCacheBackend) -> None:
    """delete(*keys) применяется к scoped ключам."""
    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await backend.set("k1", b"v1")
        await backend.set("k2", b"v2")
        await backend.set("k3", b"v3")
        await backend.delete("k1", "k3")
        assert await backend.get("k1") is None
        assert await backend.get("k2") == b"v2"
        assert await backend.get("k3") is None


async def test_feature_flag_off_passes_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """При выключенном feature-flag — wrapper делегирует напрямую."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(
        features_module.feature_flags,
        "tenant_cache_prefix_enabled",
        False,
        raising=False,
    )
    backend = TenantCacheBackend(MemoryBackend(maxsize=8, default_ttl=60))

    with tenant_scope(TenantContext(tenant_id="bank_a")):
        await backend.set("k", b"v")
    with tenant_scope(TenantContext(tenant_id="bank_b")):
        # Без префикса — tenant B видит запись tenant A
        leak = await backend.get("k")
        assert leak == b"v"


async def test_custom_tenant_provider() -> None:
    """Кастомный tenant_provider — для unit-isolation без ContextVar."""
    holder = {"tenant_id": "bank_x"}

    def _provider() -> TenantContext | None:
        return TenantContext(tenant_id=holder["tenant_id"])

    backend = TenantCacheBackend(
        MemoryBackend(maxsize=8, default_ttl=60), tenant_provider=_provider
    )
    await backend.set("k", b"v-x")
    holder["tenant_id"] = "bank_y"
    leak = await backend.get("k")
    assert leak is None
