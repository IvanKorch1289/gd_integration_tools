"""ConnectorHealthMixin — единый timing/exception helper для health().

S203 W1: консолидация ``SinkHealthMixin`` + ``SourceHealthMixin`` в один
mixin (раньше — две почти идентичные копии по 41 строке).

Использование::

    class MyConnector(ConnectorHealthMixin):
        async def health(self, mode: str = "fast") -> HealthResult:
            return await self._timed_health(self._probe, mode)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.clients.base_connector import (
        HealthMode,
        HealthResult,
    )

__all__ = ("ConnectorHealthMixin",)


class ConnectorHealthMixin:
    """Предоставляет ``_timed_health()`` для реализации health() в sinks/sources."""

    async def _timed_health(
        self, probe: Callable[[], Any], mode: HealthMode,
    ) -> HealthResult:
        """Оборачивает probe-колбек в timing + exception handling.

        Args:
            probe: Async/sync callable возвращающая dict (legacy) или HealthResult.
            mode: ``"fast"`` или ``"deep"`` — пробрасывается в HealthResult.

        Returns:
            HealthResult с ``status``/``latency_ms``/``error``.

        """
        start = time.perf_counter()
        try:
            from src.backend.infrastructure.clients.base_connector import HealthResult

            extra = await probe() if callable(probe) else {}
            latency_ms = (time.perf_counter() - start) * 1000.0
            details = extra if isinstance(extra, dict) else {}
            return HealthResult.ok(latency_ms=latency_ms, mode=mode, **details)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms,
            )
