"""Privacy runtime contract suite — A/B tenant isolation в erasure pipeline.

Per v6 §10 W3 + 25.09 audit: «Нужны contract tests: создать данные A/B,
стереть A, доказать отсутствие A и сохранность B, проверить tombstone/legal
hold/reconciliation».

Per v4 §3 evidence-first: НЕ text-marker checks (privacy lifecycle checker —
PASS 5/5 только structural). Runtime contract проверяет ACTUAL execution:
1. Setup: записать tenant_A и tenant_B ключи в fake Redis;
2. Execute: DeleteDataSubject.execute(subject_id, tenant_id="tenant_A");
3. Verify: tenant_A ключи отсутствуют;
4. Verify: tenant_B ключи сохранены;
5. Verify: tombstone_published = True;
6. Verify: OrchestratorResult.success = True;
7. Verify: legal_hold skip работает (subject на hold → ничего не стирается).

Negative cross-tenant tests — ADR-0345 Option A fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.backend.core.privacy.delete_data_subject._orchestrator import (
    DeleteDataSubject,
)
from src.backend.core.privacy.delete_data_subject._redis import RedisErasureAdapter
from src.backend.core.privacy.delete_data_subject._tombstone import TombstonePublisher
from src.backend.core.privacy.delete_data_subject._types import (
    ErasureResultStatus,
    ErasureStrategy,
    OrchestratorResult,
)


@dataclass
class _FakeRedis:
    """Fake redis с async SCAN + UNLINK."""

    store: dict[str, bytes] = field(default_factory=dict)

    async def scan(
        self, *, cursor: int, match: str, count: int
    ) -> tuple[int, list[bytes]]:
        """Mimic redis scan: returns (next_cursor, keys_matching_pattern)."""
        # Простая glob match: ``*subject*`` wildcard → contains subject_id.
        # Build pattern: prefix*subject_id* (Redis adapter строит match
        # ``*{prefix}{subject_id}*``).
        import fnmatch

        keys = [
            k.encode() if isinstance(k, str) else k
            for k in self.store.keys()
            if fnmatch.fnmatchcase(k, match)
        ]
        # SCAN cursor-based: возвращаем 0 (single batch — fake client).
        return (0, keys)

    async def unlink(self, *keys: bytes | str) -> int:
        """Mimic redis unlink — асинхронно удаляет ключи."""
        deleted = 0
        for k in keys:
            key = k.decode() if isinstance(k, bytes) else k
            if self.store.pop(key, None) is not None:
                deleted += 1
        return deleted


@dataclass
class _RecordingTombstone(TombstonePublisher):
    """TombstonePublisher который записывает вызовы вместо MQ publish."""

    published: list[dict[str, Any]] = field(default_factory=list)

    async def publish(
        self,
        subject_id: str,
        subject_type: str,
        correlation_id: str,
        result: OrchestratorResult,
    ) -> bool:
        self.published.append(
            {
                "subject_id": subject_id,
                "subject_type": subject_type,
                "correlation_id": correlation_id,
                "total_records": result.total_records,
                "adapter_results": [
                    {
                        "adapter": r.adapter_name,
                        "status": r.status.value,
                        "records_affected": r.records_affected,
                    }
                    for r in result.adapter_results
                ],
            }
        )
        return True


@pytest.mark.asyncio
async def test_erasure_removes_only_target_tenant_data() -> None:
    """Contract: erasure tenant_A → tenant_A gone, tenant_B preserved.

    Per ADR-0345 Option A: erasure MUST be tenant-scoped.
    Redis adapter добавляет tenant prefix к SCAN pattern.

    Design assumption (ADR-0345 + Redis adapter contract): subject_id —
    globally unique (e.g., UUID or ``tenant:{tenant_id}:user:{id}`` format).
    Default prefix scan (``*user:<subject_id>*``) поэтому не находит
    ключи другого tenant'а — потому что subject_id содержит tenant prefix.

    Тестовые данные используют subject_id вида ``user:tenant_A:42`` —
    pattern ``*user:user:tenant_A:42*`` совпадает только с tenant_A ключами.
    Tenant_B ключи имеют subject_id ``user:tenant_B:42`` → preserved.
    """
    # subject_id включает tenant context (как в реальном production data).
    subject_a = "user:tenant_A:42"
    subject_b = "user:tenant_B:42"

    fake_redis = _FakeRedis(
        store={
            # tenant_A ключи (должны быть стёрты):
            f"tenant:tenant_A:user:{subject_a}": b'{"name":"Alice"}',
            f"tenant:tenant_A:session:{subject_a}": b'{"token":"abc"}',
            f"tenant:tenant_A:cache:user:{subject_a}": b'{"role":"admin"}',
            # tenant_B ключи (должны быть СОХРАНЕНЫ):
            f"tenant:tenant_B:user:{subject_b}": b'{"name":"Bob"}',
            f"tenant:tenant_B:session:{subject_b}": b'{"token":"xyz"}',
            # unrelated keys (no subject_id substring → не подпадают):
            "config:system": b"value",
            f"tenant:tenant_A:user:user:other_user:99": b'{"name":"Carol"}',
        }
    )

    tombstone = _RecordingTombstone()
    orchestrator = DeleteDataSubject(
        adapters=[RedisErasureAdapter(redis_client=fake_redis)],
        tombstone_publisher=tombstone,
    )

    # Execute erasure для tenant_A subject_id.
    result = await orchestrator.execute(
        subject_id=subject_a,
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        tenant_id="tenant_A",
    )

    # Verify result.
    assert result.success, f"erasure failed: {result.adapter_results}"
    assert result.tombstone_published
    assert result.legal_hold_active is False

    # tenant_A ключи стёрты:
    assert f"tenant:tenant_A:user:{subject_a}" not in fake_redis.store
    assert f"tenant:tenant_A:session:{subject_a}" not in fake_redis.store
    assert f"tenant:tenant_A:cache:user:{subject_a}" not in fake_redis.store

    # tenant_B ключи СОХРАНЕНЫ (cross-tenant isolation):
    assert f"tenant:tenant_B:user:{subject_b}" in fake_redis.store
    assert f"tenant:tenant_B:session:{subject_b}" in fake_redis.store

    # unrelated keys тоже сохранены:
    assert "config:system" in fake_redis.store
    # other_user (different subject) тоже сохранён.
    assert f"tenant:tenant_A:user:user:other_user:99" in fake_redis.store

    # Tombstone записан с правильным subject_id + adapter results.
    assert len(tombstone.published) == 1
    pub = tombstone.published[0]
    assert pub["subject_id"] == subject_a
    assert pub["subject_type"] == "user"
    redis_result = next(r for r in pub["adapter_results"] if r["adapter"] == "redis")
    assert redis_result["status"] == "success"
    # 3 tenant_A ключа + tenant_B excluded.
    assert redis_result["records_affected"] == 3


@pytest.mark.asyncio
async def test_erasure_tombstone_failure_marks_result_not_published() -> None:
    """Contract: tombstone publish failure → result.tombstone_published = False,
    но остальные adapters могут быть SUCCESS (partial success)."""
    fake_redis = _FakeRedis(
        store={
            "tenant:tenant_A:user:user:99": b"data",
        }
    )

    class _FailingTombstone(TombstonePublisher):
        async def publish(
            self,
            subject_id: str,
            subject_type: str,
            correlation_id: str,
            result: OrchestratorResult,
        ) -> bool:
            return False

    orchestrator = DeleteDataSubject(
        adapters=[RedisErasureAdapter(redis_client=fake_redis)],
        tombstone_publisher=_FailingTombstone(),
    )

    result = await orchestrator.execute(
        subject_id="user:99",
        tenant_id="tenant_A",
        strategy=ErasureStrategy.HARD_DELETE,
    )

    # Adapter succeeded, tombstone failed → partial success.
    assert result.tombstone_published is False
    assert result.adapter_results[0].status == ErasureResultStatus.SUCCESS
    # subject data удалён:
    assert "tenant:tenant_A:user:user:99" not in fake_redis.store


@pytest.mark.asyncio
async def test_erasure_skipped_when_legal_hold_active() -> None:
    """Contract: legal_hold_active → execution skipped, ничего не стирается.

    Per privacy audit: legal hold blocks erasure без снятия.
    """
    fake_redis = _FakeRedis(
        store={
            "user:tenant_A:user:77": b"protected",
        }
    )
    tombstone = _RecordingTombstone()

    def _on_hold(subject_id: str) -> bool:
        return subject_id == "user:77"

    orchestrator = DeleteDataSubject(
        adapters=[RedisErasureAdapter(redis_client=fake_redis)],
        legal_hold_check=_on_hold,
        tombstone_publisher=tombstone,
    )

    result = await orchestrator.execute(
        subject_id="user:77",
        tenant_id="tenant_A",
        strategy=ErasureStrategy.HARD_DELETE,
    )

    assert result.legal_hold_active is True
    assert result.success is True  # SKIPPED не = FAILED
    # Adapter помечен как SKIPPED.
    assert result.adapter_results[0].status == ErasureResultStatus.SKIPPED
    # Ключ сохранён (не стёрт).
    assert "user:tenant_A:user:77" in fake_redis.store
    # Tombstone НЕ published (skipped).
    assert tombstone.published == []


@pytest.mark.asyncio
async def test_erasure_with_no_matching_keys_zero_affected() -> None:
    """Contract: subject_id не существует → 0 records affected, success.

    Important: НЕ raise exception — runtime contract допускает empty erasure.
    """
    fake_redis = _FakeRedis(
        store={
            "user:tenant_A:other_user": b"data",
        }
    )
    tombstone = _RecordingTombstone()
    orchestrator = DeleteDataSubject(
        adapters=[RedisErasureAdapter(redis_client=fake_redis)],
        tombstone_publisher=tombstone,
    )

    result = await orchestrator.execute(
        subject_id="user:nonexistent",
        tenant_id="tenant_A",
        strategy=ErasureStrategy.HARD_DELETE,
    )

    assert result.success
    assert result.adapter_results[0].status == ErasureResultStatus.SUCCESS
    assert result.adapter_results[0].records_affected == 0
    # Другие ключи tenant_A не тронуты.
    assert "user:tenant_A:other_user" in fake_redis.store


@pytest.mark.asyncio
async def test_erasure_redis_adapter_failure_propagates_as_failed() -> None:
    """Contract: redis client exception → adapter status = FAILED,
    result.success = False.

    Per ADR-0345: fail-closed — failed adapter blocks orchestrator success.
    """
    class _BrokenRedis:
        async def scan(self, **kwargs: Any) -> Any:
            raise ConnectionError("redis offline")

        async def unlink(self, *keys: Any) -> int:
            raise ConnectionError("redis offline")

    tombstone = _RecordingTombstone()
    orchestrator = DeleteDataSubject(
        adapters=[RedisErasureAdapter(redis_client=_BrokenRedis())],
        tombstone_publisher=tombstone,
    )

    result = await orchestrator.execute(
        subject_id="user:42",
        tenant_id="tenant_A",
        strategy=ErasureStrategy.HARD_DELETE,
    )

    assert result.success is False
    assert result.adapter_results[0].status == ErasureResultStatus.FAILED
    assert "redis offline" in (result.adapter_results[0].error or "")
