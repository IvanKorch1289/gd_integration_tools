"""SourceHealthMixin — helper для sources: timing + exception handling для health().

Использование::

    class MySource(SourceHealthMixin):
        async def health(self, mode="fast") -> HealthResult:
            return await self._timed_health(self._probe, mode)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.backend.infrastructure.clients.base_connector import (
    HealthMode,
    HealthResult,
)

__all__ = ("SourceHealthMixin",)


class SourceHealthMixin:
    """Предоставляет ``_timed_health()`` для реализации health() в sources."""

    async def _timed_health(
        self, probe: Callable[[], Any], mode: HealthMode
    ) -> HealthResult:
        """Оборачивает probe-колбек в timing + exception handling."""
        start = time.perf_counter()
        try:
            extra = await probe() if callable(probe) else {}
            latency_ms = (time.perf_counter() - start) * 1000.0
            details = extra if isinstance(extra, dict) else {}
            return HealthResult.ok(latency_ms=latency_ms, mode=mode, **details)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
