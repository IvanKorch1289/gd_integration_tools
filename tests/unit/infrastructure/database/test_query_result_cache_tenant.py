"""Wave 16 / X4: ключ ``QueryResultCache`` обязан включать tenant_id.

Кэш результатов SQL жил на shared-бэкенде (Redis/KeyDB) без tenant'а в
ключе: запрос одного tenant'а возвращал закэшированные строки другого.
Сейчас кэш не используется production-кодом, но при включении это —
кросс-тенантная утечка (ADR-0383).
"""

from __future__ import annotations

import pytest

from src.backend.core.tenancy import TenantContext, tenant_scope
from src.backend.infrastructure.cache.backends.memory import MemoryBackend
from src.backend.infrastructure.database.query_result_cache import QueryResultCache

SQL = "SELECT id, email FROM docs WHERE id = :id"
PARAMS = {"id": 1}


@pytest.mark.asyncio
async def test_cache_key_includes_tenant() -> None:
    """Ключ кэша различается для разных tenant'ов.

    Raises:
        AssertionError: Если ключ не содержит tenant_id.
    """
    cache = QueryResultCache(backend=MemoryBackend())

    with tenant_scope(TenantContext(tenant_id="tenant-a")):
        key_a = cache._make_key("main", SQL, PARAMS)
    with tenant_scope(TenantContext(tenant_id="tenant-b")):
        key_b = cache._make_key("main", SQL, PARAMS)

    assert key_a != key_b, "ключ кэша не учитывает tenant_id"
    assert "tenant-a" in key_a
    assert "tenant-b" in key_b


@pytest.mark.asyncio
async def test_cache_does_not_serve_other_tenant_rows() -> None:
    """Значение, закэшированное tenant'ом A, не отдаётся tenant'у B.

    Raises:
        AssertionError: Если данные другого tenant'а утёкли из кэша.
    """
    cache = QueryResultCache(backend=MemoryBackend())

    with tenant_scope(TenantContext(tenant_id="tenant-a")):
        await cache.set("main", SQL, PARAMS, [{"id": 1, "email": "a@example.com"}])

    with tenant_scope(TenantContext(tenant_id="tenant-b")):
        assert await cache.get("main", SQL, PARAMS) is None

    with tenant_scope(TenantContext(tenant_id="tenant-a")):
        assert await cache.get("main", SQL, PARAMS) == [
            {"id": 1, "email": "a@example.com"}
        ]
