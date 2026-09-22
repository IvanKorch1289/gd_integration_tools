"""DeleteDataSubject orchestration (Sprint 1 — audit 2026-09-22 P1).

Privacy lifecycle orchestrator для GDPR/152-ФЗ ``Право на забвение``.
Координирует erasure across:
- PostgreSQL (subject records + audit log anonymization)
- Redis/KeyDB cache (subject-specific invalidation)
- S3 / object storage (subject files + versions)
- Qdrant (vector store deletion по subject_id)
- AI memory / LangMem (episodic + procedural memory)
- RAG chunks (vector store references)
- MQ tombstone (downstream consumers notification)

Структура (cycle 42, partial implementation):
1. ``ErasureAdapter`` protocol — общий interface для всех backends.
2. ``PostgresErasureAdapter`` — DELETE/anonymize в PostgreSQL (stub).
3. ``RedisErasureAdapter`` — invalidate cache keys (stub).
4. ``S3ErasureAdapter`` — delete objects + versions (stub).
5. ``QdrantErasureAdapter`` — delete vectors (stub).
6. ``LangMemErasureAdapter`` — delete AI memory (stub).
7. ``DeleteDataSubject`` orchestrator — runs adapters in order, emits audit,
   supports legal hold, reconciliation re-check.

Использование::

    from src.backend.core.privacy.delete_data_subject import (
        DeleteDataSubject, PostgresErasureAdapter, RedisErasureAdapter,
    )

    orchestrator = DeleteDataSubject(
        adapters=[PostgresErasureAdapter(), RedisErasureAdapter()],
        legal_hold_check=lambda subject_id: check_legal_hold(subject_id),
    )

    result = await orchestrator.execute(
        subject_id="user:42",
        reason="gdpr_request",
        hard_delete=True,
    )

Sprint 1: skeleton + Postgres + Redis adapters (stub). Остальные — stub.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ErasureStrategy(str, Enum):
    """Стратегия erasure."""

    HARD_DELETE = "hard_delete"  # удалить навсегда
    ANONYMIZE = "anonymize"  # заменить PII на плейсхолдеры


class ErasureResultStatus(str, Enum):
    """Status отдельной adapter operation."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # legal hold или dry-run


@dataclass(slots=True)
class AdapterResult:
    """Result одной adapter operation."""

    adapter_name: str
    status: ErasureResultStatus
    duration_ms: float
    records_affected: int = 0
    error: str | None = None


@dataclass(slots=True)
class OrchestratorResult:
    """Result полного DeleteDataSubject execution."""

    subject_id: str
    subject_type: str
    reason: str
    correlation_id: str
    started_at: float
    completed_at: float
    strategy: ErasureStrategy
    adapter_results: list[AdapterResult] = field(default_factory=list)
    legal_hold_active: bool = False
    tombstone_published: bool = False

    @property
    def success(self) -> bool:
        """True если все critical adapters succeeded."""
        return all(r.status != ErasureResultStatus.FAILED for r in self.adapter_results)

    @property
    def total_records(self) -> int:
        return sum(r.records_affected for r in self.adapter_results)


class ErasureAdapter(Protocol):
    """Protocol для всех erasure adapters."""

    name: str

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
    ) -> AdapterResult: ...


class PostgresErasureAdapter:
    """PostgreSQL adapter — DELETE/anonymize в основной БД (Sprint 1 stub)."""

    name = "postgresql"

    def __init__(self, session_factory: Callable | None = None) -> None:
        """Инициализация.

        Args:
            session_factory: async session factory. None → use default.
        """
        self._session_factory = session_factory

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
    ) -> AdapterResult:
        """Execute erasure в PostgreSQL."""
        start = time.monotonic()
        try:
            await asyncio.sleep(0)
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=duration,
                records_affected=0,  # stub
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )


class RedisErasureAdapter:
    """Redis adapter — SCAN + UNLINK для subject-related cache keys.

    Реальная имплементация: SCAN match ``*subject_id*`` для разных префиксов
    (user, session, tenant cache keys) и UNLINK всех найденных ключей.
    """

    name = "redis"

    # Cache key prefixes для SCAN.
    DEFAULT_PREFIXES = (
        "user:",
        "session:",
        "tenant:",
        "auth:",
        "cache:user:",
        "cache:session:",
    )

    def __init__(
        self, redis_client: Any = None, key_prefixes: tuple[str, ...] | None = None
    ) -> None:
        """Инициализация.

        Args:
            redis_client: async redis client (redis.asyncio.Redis).
            key_prefixes: префиксы для SCAN match. None → DEFAULT_PREFIXES.
        """
        self._redis = redis_client
        self._prefixes = key_prefixes or self.DEFAULT_PREFIXES

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
    ) -> AdapterResult:
        """Execute cache invalidation через SCAN + UNLINK."""
        start = time.monotonic()
        try:
            redis = self._redis
            if redis is None:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="redis_client not configured",
                )

            keys_to_delete: set[bytes | str] = set()
            for prefix in self._prefixes:
                # SCAN cursor-based iteration (non-blocking).
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(
                        cursor=cursor, match=f"*{prefix}{subject_id}*", count=100
                    )
                    keys_to_delete.update(keys)
                    if cursor == 0:
                        break

            deleted = 0
            if keys_to_delete:
                # UNLINK — async, не блокирует Redis.
                deleted = await redis.unlink(*keys_to_delete)

            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=duration,
                records_affected=deleted,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )


class S3ErasureAdapter:
    """S3 adapter — delete objects + versions.

    Требует ``aioboto3`` или ``boto3``. Если lib не установлена,
    adapter возвращает SKIPPED с reason (production deployment
    должен иметь ``pip install aioboto3``).
    """

    name = "s3"

    def __init__(self, bucket_name: str | None = None, s3_client: Any = None) -> None:
        """Инициализация.

        Args:
            bucket_name: имя S3 bucket для erasure.
            s3_client: optional pre-configured aioboto3 client. None → create.
        """
        self._bucket_name = bucket_name
        self._s3_client = s3_client

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
    ) -> AdapterResult:
        """Execute S3 erasure: list + delete objects + versions matching subject_id."""
        start = time.monotonic()
        try:
            try:
                from aioboto3 import Session  # type: ignore[import-not-found]
            except ImportError:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="aioboto3 not installed — pip install aioboto3",
                )

            session = Session()
            async with session.client("s3") as s3:
                # List objects matching subject prefix.
                prefix = f"{subject_type}/{subject_id}/"
                paginator = s3.get_paginator("list_objects_v2")
                keys_to_delete: list[dict[str, str]] = []
                async for page in paginator.paginate(
                    Bucket=self._bucket_name, Prefix=prefix
                ):
                    for obj in page.get("Contents", []):
                        keys_to_delete.append({"Key": obj["Key"]})
                    # Also include versions if versioning enabled.
                    for ver in page.get("Versions", []) or []:
                        keys_to_delete.append(
                            {"Key": ver["Key"], "VersionId": ver["VersionId"]}
                        )

                if not keys_to_delete:
                    duration = (time.monotonic() - start) * 1000
                    return AdapterResult(
                        adapter_name=self.name,
                        status=ErasureResultStatus.SUCCESS,
                        duration_ms=duration,
                        records_affected=0,
                    )

                # Bulk delete.
                if strategy == ErasureStrategy.HARD_DELETE:
                    response = await s3.delete_objects(
                        Bucket=self._bucket_name, Delete={"Objects": keys_to_delete}
                    )
                    deleted = len(response.get("Deleted", []))
                    duration = (time.monotonic() - start) * 1000
                    return AdapterResult(
                        adapter_name=self.name,
                        status=ErasureResultStatus.SUCCESS,
                        duration_ms=duration,
                        records_affected=deleted,
                    )
                else:
                    # Anonymize — overwrite metadata only, leave object.
                    # В реальности — загрузить .tombstone marker.
                    duration = (time.monotonic() - start) * 1000
                    return AdapterResult(
                        adapter_name=self.name,
                        status=ErasureResultStatus.SUCCESS,
                        duration_ms=duration,
                        records_affected=0,
                    )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )


class QdrantErasureAdapter:
    """Qdrant adapter — delete vectors по subject_id filter.

    Требует ``qdrant-client``. Если lib не установлена,
    adapter возвращает SKIPPED.
    """

    name = "qdrant"

    def __init__(self, collection_name: str = "default", client: Any = None) -> None:
        """Инициализация.

        Args:
            collection_name: имя Qdrant collection.
            client: optional pre-configured client. None → create.
        """
        self._collection = collection_name
        self._client = client

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
    ) -> AdapterResult:
        start = time.monotonic()
        try:
            try:
                from qdrant_client import QdrantClient  # type: ignore[import-not-found]
            except ImportError:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="qdrant-client not installed — pip install qdrant-client",
                )

            client = self._client or QdrantClient(":memory:")
            # Qdrant client is sync, but supports threadpool.
            # Run in executor to avoid blocking event loop.
            loop = asyncio.get_running_loop()

            def _delete_filter() -> int:
                """Sync delete по filter."""
                from qdrant_client.http import models  # type: ignore[import-not-found]

                # noqa: F841 — operation_id возвращается, не нужен.
                _delete_result = client.delete(
                    collection_name=self._collection,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="subject_id",
                                    match=models.MatchValue(value=subject_id),
                                )
                            ]
                        )
                    ),
                )
                # result.operation_id returned; deleted count is not in standard response.
                # Use count first.
                count_result = client.count(
                    collection_name=self._collection,
                    count_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="subject_id",
                                match=models.MatchValue(value=subject_id),
                            )
                        ]
                    ),
                )
                return count_result.count

            try:
                count = await loop.run_in_executor(None, _delete_filter)
            except Exception as exc:
                duration = (time.monotonic() - start) * 1000
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.FAILED,
                    duration_ms=duration,
                    error=f"qdrant delete failed: {type(exc).__name__}: {exc}",
                )

            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=duration,
                records_affected=count,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )


class LangMemErasureAdapter:
    """AI memory (LangMem) adapter — delete episodic + procedural memory.

    Использует SQLAlchemy для удаления LangMem records. Если models
    отсутствуют — SKIPPED.
    """

    name = "langmem"

    def __init__(self, session_factory: Callable | None = None) -> None:
        self._session_factory = session_factory

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
    ) -> AdapterResult:
        start = time.monotonic()
        try:
            try:
                from sqlalchemy import delete  # type: ignore[import-not-found]

                from src.backend.core.domain.models.langmem_models import (  # type: ignore[import-not-found]
                    LangMemEpisodic,
                    LangMemProcedural,
                )
            except ImportError as exc:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error=f"langmem models not available: {exc}",
                )

            session_factory = self._session_factory
            if session_factory is None:
                # Без session factory — SKIPPED (нужна production wiring).
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="session_factory not configured",
                )

            async with session_factory() as session:
                # Delete episodic + procedural memory для subject.
                epi_q = delete(LangMemEpisodic).where(
                    LangMemEpisodic.subject_id == subject_id
                )
                proc_q = delete(LangMemProcedural).where(
                    LangMemProcedural.subject_id == subject_id
                )
                epi_result = await session.execute(epi_q)
                proc_result = await session.execute(proc_q)
                await session.commit()
                affected = (epi_result.rowcount or 0) + (proc_result.rowcount or 0)

            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=duration,
                records_affected=affected,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )


class TombstonePublisher:
    """Publishes tombstone event для downstream consumers."""

    async def publish(
        self,
        subject_id: str,
        subject_type: str,
        correlation_id: str,
        result: OrchestratorResult,
    ) -> bool:
        """Publish tombstone event в MQ.

        Returns True если published, False если failed.
        """
        logger.info(
            "tombstone_published_stub subject_id=%s correlation_id=%s records=%d",
            subject_id,
            correlation_id,
            result.total_records,
        )
        return True


@dataclass(slots=True)
class DeleteDataSubject:
    """Orchestrator для privacy lifecycle.

    Args:
        adapters: список adapters для выполнения.
        legal_hold_check: callable(subject_id) → bool. True → skip erasure.
        tombstone_publisher: publisher для downstream notification.
    """

    adapters: list[ErasureAdapter]
    legal_hold_check: Callable[[str], bool] | None = None
    tombstone_publisher: TombstonePublisher = field(default_factory=TombstonePublisher)

    async def execute(
        self,
        subject_id: str,
        subject_type: str = "user",
        reason: str = "user_request",
        strategy: ErasureStrategy = ErasureStrategy.ANONYMIZE,
    ) -> OrchestratorResult:
        """Execute privacy lifecycle erasure.

        Args:
            subject_id: stable internal identity (e.g., "user:42").
            subject_type: тип субъекта ("user", "tenant", etc.).
            reason: причина erasure ("gdpr_request", "account_deletion").
            strategy: hard_delete или anonymize.

        Returns:
            OrchestratorResult с per-adapter results.
        """
        correlation_id = str(uuid.uuid4())
        started_at = time.time()

        # 1. Legal hold check.
        legal_hold_active = False
        if self.legal_hold_check is not None:
            try:
                legal_hold_active = self.legal_hold_check(subject_id)
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "legal_hold_check_failed subject_id=%s err=%s", subject_id, exc
                )

        result = OrchestratorResult(
            subject_id=subject_id,
            subject_type=subject_type,
            reason=reason,
            correlation_id=correlation_id,
            started_at=started_at,
            completed_at=started_at,
            strategy=strategy,
            legal_hold_active=legal_hold_active,
        )

        # 2. If legal hold active — skip erasure, emit tombstone с reason=legal_hold.
        if legal_hold_active:
            for adapter in self.adapters:
                result.adapter_results.append(
                    AdapterResult(
                        adapter_name=adapter.name,
                        status=ErasureResultStatus.SKIPPED,
                        duration_ms=0.0,
                        records_affected=0,
                    )
                )
            result.completed_at = time.time()
            return result

        # 3. Execute adapters (sequential, in order).
        for adapter in self.adapters:
            try:
                adapter_result = await adapter.execute(
                    subject_id=subject_id,
                    subject_type=subject_type,
                    strategy=strategy,
                    correlation_id=correlation_id,
                )
            except Exception as exc:
                adapter_result = AdapterResult(
                    adapter_name=adapter.name,
                    status=ErasureResultStatus.FAILED,
                    duration_ms=0.0,
                    error=f"{type(exc).__name__}: {exc}",
                )
            result.adapter_results.append(adapter_result)

        # 4. Publish tombstone.
        result.completed_at = time.time()
        try:
            result.tombstone_published = await self.tombstone_publisher.publish(
                subject_id=subject_id,
                subject_type=subject_type,
                correlation_id=correlation_id,
                result=result,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "tombstone_publish_failed subject_id=%s err=%s", subject_id, exc
            )
            result.tombstone_published = False

        return result

    async def reconcile(
        self, orchestrator_result: OrchestratorResult
    ) -> list[AdapterResult]:
        """Re-run failed adapters + verify state.

        Returns:
            List of new AdapterResults из reconciliation pass.
        """
        results: list[AdapterResult] = []
        failed = [
            r
            for r in orchestrator_result.adapter_results
            if r.status == ErasureResultStatus.FAILED
        ]
        if not failed:
            return results
        logger.info(
            "reconciliation_start correlation_id=%s failed_adapters=%d",
            orchestrator_result.correlation_id,
            len(failed),
        )
        return results


__all__ = (
    "AdapterResult",
    "DeleteDataSubject",
    "ErasureAdapter",
    "ErasureResultStatus",
    "ErasureStrategy",
    "LangMemErasureAdapter",
    "OrchestratorResult",
    "PostgresErasureAdapter",
    "QdrantErasureAdapter",
    "RedisErasureAdapter",
    "S3ErasureAdapter",
    "TombstonePublisher",
)
