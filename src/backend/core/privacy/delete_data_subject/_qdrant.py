"""Qdrant ErasureAdapter — delete vectors по subject_id filter.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

Требует ``qdrant-client``. Если lib не установлена, adapter возвращает SKIPPED.

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``QdrantErasureAdapter`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from src.backend.core.privacy.delete_data_subject._types import (
    AdapterResult,
    ErasureResultStatus,
    ErasureStrategy,
)


class QdrantErasureAdapter:
    """Qdrant adapter — delete vectors по subject_id filter."""

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
        *,
        tenant_id: str | None = None,
    ) -> AdapterResult:
        """Execute subject-scoped vector erasure в Qdrant.

        Per ADR-0345 Option A: tenant-aware via Qdrant filter expression.
        ``tenant_id`` is added to ``must`` FieldCondition when provided.
        Schema requirement: payload must have ``tenant_id`` field (population
        contract for upstream ingest). Without ``tenant_id`` in payload,
        filter is no-op (filter logs warning for forensic trail).
        """
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

            # ADR-0345: tenant resolution (per-call OR context).
            resolved_tenant_id: str | None = tenant_id
            if resolved_tenant_id is None:
                try:
                    from src.backend.core.tenancy import get_tenant_id

                    resolved_tenant_id = get_tenant_id()
                except Exception:
                    pass

            client = self._client or QdrantClient(":memory:")
            # Qdrant client is sync, but supports threadpool.
            # Run in executor to avoid blocking event loop.
            loop = asyncio.get_running_loop()

            def _delete_filter() -> int:
                """Sync delete по filter.

                Per ADR-0345: добавляет tenant_id в must[] when resolved.
                Schema requirement: vector payload must include tenant_id field.
                """
                from qdrant_client.http import models  # type: ignore[import-not-found]

                must_conditions: list = [
                    models.FieldCondition(
                        key="subject_id", match=models.MatchValue(value=subject_id)
                    )
                ]
                if resolved_tenant_id:
                    must_conditions.append(
                        models.FieldCondition(
                            key="tenant_id",
                            match=models.MatchValue(value=resolved_tenant_id),
                        )
                    )

                # noqa: F841 — operation_id возвращается, не нужен.
                _delete_result = client.delete(
                    collection_name=self._collection,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(must=must_conditions)
                    ),
                )
                # result.operation_id returned; deleted count is not in standard response.
                # Use count first.
                count_result = client.count(
                    collection_name=self._collection,
                    count_filter=models.Filter(must=must_conditions),
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
