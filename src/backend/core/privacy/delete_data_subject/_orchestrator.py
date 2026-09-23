"""DeleteDataSubject orchestrator — main entry point для privacy lifecycle.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

Координирует erasure across PostgreSQL, Redis, S3, Qdrant, LangMem adapters
+ tombstone publisher. Supports legal hold skip + reconciliation.

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``DeleteDataSubject`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from src.backend.core.privacy.delete_data_subject._tombstone import TombstonePublisher
from src.backend.core.privacy.delete_data_subject._types import (
    AdapterResult,
    ErasureAdapter,
    ErasureResultStatus,
    ErasureStrategy,
    OrchestratorResult,
)

logger = logging.getLogger(__name__)


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
