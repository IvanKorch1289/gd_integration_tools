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
