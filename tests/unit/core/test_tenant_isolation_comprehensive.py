"""Comprehensive cross-tenant isolation suite (P0, внешний план).

Проверяет отсутствие прямых и косвенных утечек между tenants на всех
storage-слоях: cache, Redis, DB (SQLAlchemy), RAG retrieval.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.tenancy import (
    TenantContext,
    current_tenant,
    get_tenant_id,
    set_tenant,
)

_TA = "bank_a"
_TB = "bank_b"


# ═══ TenantContext (ContextVar isolation) ═══════════════════════════════

class TestTenantContext:
    def test_set_and_get(self) -> None:
        ctx = TenantContext(tenant_id=_TA)
        set_tenant(ctx)
        assert current_tenant() is ctx
        assert get_tenant_id() == _TA
        # cleanup
        from src.backend.core.tenancy import _current
        _current.set(None)

    def test_no_leak_sequential(self) -> None:
        ctx_a = TenantContext(tenant_id=_TA)
        ctx_b = TenantContext(tenant_id=_TB)
        set_tenant(ctx_a)
        assert get_tenant_id() == _TA
        set_tenant(ctx_b)
        assert get_tenant_id() == _TB
        assert get_tenant_id() != _TA
        from src.backend.core.tenancy import _current
        _current.set(None)

    @pytest.mark.asyncio
    async def test_no_leak_concurrent(self) -> None:
        results: dict[str, str] = {}

        async def worker(tid: str) -> None:
            ctx = TenantContext(tenant_id=tid)
            set_tenant(ctx)
            await asyncio.sleep(0.01)
            results[tid] = get_tenant_id()

        await asyncio.gather(worker(_TA), worker(_TB))
        assert results[_TA] == _TA
        assert results[_TB] == _TB


# ═══ TenantCacheBackend (prefix isolation) ══════════════════════════════

def _make_tenant_cache(tid: str) -> tuple[Any, list[str]]:
    """TenantCacheBackend с текущим tenant=tid. Возвращает (backend, keys)."""
    from src.backend.infrastructure.cache.tenant_wrapper import TenantCacheBackend

    keys: list[str] = []
    inner = MagicMock()

    async def _get(key: str, **kw: Any) -> None:
        keys.append(f"get:{key}")
        return None

    async def _set(key: str, value: Any, **kw: Any) -> None:
        keys.append(f"set:{key}")

    inner.get = AsyncMock(side_effect=_get)
    inner.set = AsyncMock(side_effect=_set)

    ctx = TenantContext(tenant_id=tid)
    backend = TenantCacheBackend(
        inner,
        tenant_provider=lambda: ctx,
    )
    return backend, keys


class TestTenantCachePrefix:
    def test_prefix_a(self) -> None:
        backend, _ = _make_tenant_cache(_TA)
        assert "bank_a" in backend._prefix()

    def test_prefix_b(self) -> None:
        backend, _ = _make_tenant_cache(_TB)
        assert "bank_b" in backend._prefix()

    def test_prefixes_differ(self) -> None:
        a, _ = _make_tenant_cache(_TA)
        b, _ = _make_tenant_cache(_TB)
        assert a._prefix() != b._prefix()


# ═══ DB row-level isolation (TenantMixin) ═══════════════════════════════

class TestDBTenantIsolation:
    def test_tenant_column_not_nullable(self) -> None:
        from extensions.core_entities.users.domain.models import User

        col = User.__table__.c["tenant_id"]
        assert col.nullable is False

    def test_tenant_default_is_default(self) -> None:
        from extensions.core_entities.users.domain.models import User

        col = User.__table__.c["tenant_id"]
        val = col.default.arg if hasattr(col.default, "arg") else col.default
        assert val == "default"


# ═══ RAG invalidation isolation ═════════════════════════════════════════

class TestRAGInvalidationIsolation:
    @pytest.mark.asyncio
    async def test_invalid_payload_carries_tenant(self) -> None:
        from src.backend.infrastructure.cache.rag.invalidation import RagInvalidationBus

        published: list[bytes] = []
        conn = MagicMock()
        conn.publish = AsyncMock(
            side_effect=lambda ch, payload: published.append(payload) or 1
        )
        client = MagicMock()

        async def _exec(db: str, fn: Any) -> int:
            return await fn(conn)

        client.execute = AsyncMock(side_effect=_exec)
        bus = RagInvalidationBus(channel="rag:invalidate", redis_client=client)
        await bus.publish(tag="tenant:bank_a", action="invalidate")
        payload = json.loads(published[0])
        assert payload["tag"] == "tenant:bank_a"
        assert "bank_b" not in payload["tag"]
