"""LangMem ErasureAdapter — delete episodic + procedural AI memory.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

Использует SQLAlchemy для удаления LangMem records. Если models отсутствуют
— SKIPPED.

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``LangMemErasureAdapter`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from src.backend.core.privacy.delete_data_subject._types import (
    AdapterResult,
    ErasureResultStatus,
    ErasureStrategy,
)


class LangMemErasureAdapter:
    """AI memory (LangMem) adapter — delete episodic + procedural memory."""

    name = "langmem"

    def __init__(self, session_factory: Callable | None = None) -> None:
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
        """Execute memory erasure в LangMem (AI memory).

        Per ADR-0345 Option A: tenant-aware. ``tenant_id`` resolves via
        TenantContext if not provided. Schema requirement: LangMem models
        must have ``tenant_id`` column (migration deferred — separate wave).
        Without ``tenant_id`` column, filter is no-op (logs warning for
        forensic trail) — same risk as cross-tenant erasure without filter.
        """
        import logging

        logger = logging.getLogger(__name__)
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

            # ADR-0345: tenant resolution (per-call OR context).
            resolved_tenant_id: str | None = tenant_id
            if resolved_tenant_id is None:
                try:
                    from src.backend.core.tenancy import get_tenant_id

                    resolved_tenant_id = get_tenant_id()
                except Exception:
                    pass

            # ADR-0347: модели получили subject_id (миграция e5f6a7b8c9d0),
            # поэтому фильтр доступен. Проверка остаётся fail-closed: если
            # колонки нет (сильно устаревшая БД без миграции) — SKIPPED с
            # явной причиной, а НЕ молчаливое удаление по subject_id без
            # tenant-скоупа.
            has_subject_col = hasattr(LangMemEpisodic, "subject_id")
            has_tenant_col = hasattr(LangMemEpisodic, "tenant_id")
            if not has_subject_col:
                logger.warning(
                    "langmem_subject_column_unavailable subject_id=%s — "
                    "model missing subject_id column (миграция e5f6a7b8c9d0 не "
                    "применена?); erasure пропускается, чтобы не удалить "
                    "данные вне tenant-скоупа",
                    subject_id,
                )
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="langmem model missing subject_id column",
                )
            if resolved_tenant_id and not has_tenant_col:
                logger.warning(
                    "langmem_tenant_filter_unavailable "
                    "subject_id=%s tenant_id=%s — model missing tenant_id column",
                    subject_id,
                    resolved_tenant_id,
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
                # ADR-0347: subject_id теперь существует; tenant-фильтр
                # применяется по колонке ``tenant``, потому что именно так
                # модели называют tenant-поле (tenant_id отсутствует).
                epi_conditions = [LangMemEpisodic.subject_id == subject_id]
                proc_conditions = [LangMemProcedural.subject_id == subject_id]
                if resolved_tenant_id:
                    epi_conditions.append(LangMemEpisodic.tenant == resolved_tenant_id)
                    proc_conditions.append(
                        LangMemProcedural.tenant == resolved_tenant_id
                    )
                epi_q = delete(LangMemEpisodic).where(*epi_conditions)
                proc_q = delete(LangMemProcedural).where(*proc_conditions)
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
