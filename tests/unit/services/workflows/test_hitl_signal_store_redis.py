"""Unit-тесты для RedisHitlSignalStore (S207).

Использует mock redis.asyncio.Redis (без fakeredis — упрощает setup).
Mock реализует минимальный subset: hset/hget/hgetall + pipeline WATCH/MULTI.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.backend.services.workflows.hitl_service import HitlPendingSignal
from src.backend.services.workflows.hitl_signal_store_redis import RedisHitlSignalStore


def _make_signal(
    signal_id: str = "sig-1", tenant_id: str = "tenant-1"
) -> HitlPendingSignal:
    """Фабрика для тестов."""
    return HitlPendingSignal(
        signal_id=signal_id,
        workflow_id="wf-1",
        tenant_id=tenant_id,
        signal_name="hitl_approve",
        initiator="agent-1",
        title="Approve payment",
        payload={"amount": 1000},
        created_at=datetime.now(UTC),
    )


class _FakeRedis:
    """Минимальный in-memory mock Redis: hash + pipeline WATCH/MULTI."""

    def __init__(self) -> None:
        self._hash: dict[str, str] = {}

    async def hset(self, key: str, field: str, value: str) -> None:
        self._hash[field] = value

    async def hget(self, key: str, field: str) -> bytes | None:
        val = self._hash.get(field)
        return val.encode() if val else None

    async def hgetall(self, key: str) -> dict[str, bytes]:
        return {k: v.encode() for k, v in self._hash.items()}

    async def publish(self, channel: str, message: str) -> None:
        pass  # no-op для тестов


class TestRedisHitlSignalStore:
    """S207: bounded tests для RedisHitlSignalStore."""

    async def test_put_and_get_roundtrip(self) -> None:
        client = _FakeRedis()
        store = RedisHitlSignalStore(redis_client=client)
        sig = _make_signal()
        await store.put(sig)
        loaded = await store.get(sig.signal_id)
        assert loaded is not None
        assert loaded.signal_id == sig.signal_id
        assert loaded.tenant_id == sig.tenant_id
        assert loaded.payload == sig.payload

    async def test_get_missing_returns_none(self) -> None:
        client = _FakeRedis()
        store = RedisHitlSignalStore(redis_client=client)
        assert await store.get("missing") is None

    async def test_list_pending_filters_resolved(self) -> None:
        client = _FakeRedis()
        store = RedisHitlSignalStore(redis_client=client)
        s1 = _make_signal("sig-1")
        s2 = _make_signal("sig-2")
        await store.put(s1)
        await store.put(s2)
        # Resolve s1
        await store.mark_resolved("sig-1", action="approve", resolved_by="op-1")
        pending = await store.list_pending()
        assert len(pending) == 1
        assert pending[0].signal_id == "sig-2"

    async def test_list_pending_filters_by_tenant(self) -> None:
        client = _FakeRedis()
        store = RedisHitlSignalStore(redis_client=client)
        await store.put(_make_signal("sig-1", tenant_id="t-1"))
        await store.put(_make_signal("sig-2", tenant_id="t-2"))
        pending_t1 = await store.list_pending(tenant_id="t-1")
        assert len(pending_t1) == 1
        assert pending_t1[0].signal_id == "sig-1"

    async def test_mark_resolved_idempotent(self) -> None:
        """Second mark_resolved raises ValueError."""
        client = _FakeRedis()
        store = RedisHitlSignalStore(redis_client=client)
        await store.put(_make_signal("sig-1"))
        await store.mark_resolved("sig-1", action="approve", resolved_by="op-1")
        with pytest.raises(ValueError, match="already resolved"):
            await store.mark_resolved(
                "sig-1", action="reject", resolved_by="op-2"
            )

    async def test_mark_resolved_missing_raises(self) -> None:
        client = _FakeRedis()
        store = RedisHitlSignalStore(redis_client=client)
        with pytest.raises(KeyError, match="not found"):
            await store.mark_resolved(
                "missing", action="approve", resolved_by="op-1"
            )

    async def test_to_dict_from_dict_roundtrip(self) -> None:
        """HitlPendingSignal.from_dict ↔ to_dict roundtrip."""
        sig = _make_signal("sig-x")
        data = sig.to_dict()
        restored = HitlPendingSignal.from_dict(data)
        assert restored.signal_id == sig.signal_id
        assert restored.created_at == sig.created_at
        assert restored.is_resolved == sig.is_resolved

    async def test_to_dict_with_resolution(self) -> None:
        sig = _make_signal("sig-y")
        sig.resolved_at = datetime.now(UTC)
        sig.resolved_action = "approve"
        sig.resolved_by = "op-1"
        data = sig.to_dict()
        restored = HitlPendingSignal.from_dict(data)
        assert restored.is_resolved is True
        assert restored.resolved_action == "approve"
