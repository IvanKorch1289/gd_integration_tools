"""PostgreSQL ErasureAdapter — DELETE/anonymize в основной БД.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module). Stub-implementation: реальная DELETE/anonymize логика
будет добавлена в Sprint 4+ (требует tenant-aware queries).

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``PostgresErasureAdapter`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from src.backend.core.privacy.delete_data_subject._types import (  # noqa: F401 — re-export
    AdapterResult,
    ErasureResultStatus,
    ErasureStrategy,
)


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
