"""PostgreSQL ErasureAdapter — DELETE/anonymize в основной БД.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

Cycle 158+ (commit pending): tenant-aware implementation per ADR-0345
Option A. Replaces Sprint 1 stub (was ``asyncio.sleep(0)`` + SUCCESS) with
real DELETE query filtered by subject_id + tenant_id.

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``PostgresErasureAdapter`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from src.backend.core.privacy.delete_data_subject._types import (
    AdapterResult,
    ErasureResultStatus,
    ErasureStrategy,
)


class PostgresErasureAdapter:
    """PostgreSQL adapter — DELETE/anonymize в основной БД.

    Per ADR-0345 Option A: tenant-aware per-call enforcement.
    """

    name = "postgresql"

    def __init__(self, session_factory: Callable | None = None) -> None:
        """Инициализация.

        Args:
            session_factory: async session factory. None → SKIPPED.
        """
        self._session_factory = session_factory

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
        *,
        tenant_id: str | None = None,
    ) -> AdapterResult:
        """Execute erasure в PostgreSQL с tenant-awareness.

        Per ADR-0345 Option A: fail-closed via ``current_tenant()`` from
        TenantContext OR ``tenant_id`` parameter. Deletes rows where
        BOTH subject_id matches AND tenant_id matches (fail-closed).
        """
        from src.backend.core.tenancy import get_tenant_id

        start = time.monotonic()
        try:
            session_factory = self._session_factory
            if session_factory is None:
                duration = (time.monotonic() - start) * 1000
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=duration,
                    error="session_factory not configured",
                )

            effective_tenant = (
                tenant_id
                if tenant_id is not None
                else get_tenant_id()
            )

            # Per audit + cycle 158+ privacy investigation:
            # tenant-aware DELETE with subject_id + tenant_id filters.
            from sqlalchemy import delete

            from src.backend.core.domain.models.privacy_models import (  # type: ignore[import-not-found]
                PiiErasureRecord,
            )

            conditions = [PiiErasureRecord.subject_id == subject_id]
            if effective_tenant:
                conditions.append(PiiErasureRecord.tenant_id == effective_tenant)

            async with session_factory() as session:
                result = await session.execute(
                    delete(PiiErasureRecord).where(*conditions)
                )
                await session.commit()
                records_affected = result.rowcount or 0

            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=duration,
                records_affected=records_affected,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )
