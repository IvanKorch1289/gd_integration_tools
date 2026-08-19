"""Sprint 18 P1-14: Protocol-based middleware interface (eliminate infrastructure→dsl).

Originally :class:`dsl.engine.middleware.ProcessorMiddleware` — DSL layer
определял абстракцию, которую инфраструктурные middlewares (metrics, tracing)
импортировали. Это создавало layer violation ``infrastructure → dsl``.

P1-14 fix:
* :class:`ProcessorMiddleware` moved сюда (core/interfaces/middleware.py) —
  core layer определяет generic Protocol.
* :mod:`dsl.engine.middleware` re-exports его для backward-compat.
* Infrastructure middlewares (metrics, tracing) импортируют из core/interfaces.

Ponytail: Protocol + dependency injection, не требует переписывать существующий
ABC-based код. ABC-класс в dsl/engine/middleware.py — теперь thin wrapper
вокруг Protocol.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProcessorMiddleware(Protocol):
    """Generic middleware interface для DSL-процессоров и observability.

    Используется двумя категориями consumers:
    * DSL middleware chain (dsl/engine/middleware.py) — для cross-cutting
      concerns в pipeline execution (timeout, error capture, correlation).
    * Observability middlewares (infrastructure/observability/{metrics,tracing}.py)
      — для метрик + трассировки процессоров.

    Protocol (vs ABC) позволяет infrastructure layer импортировать этот
    interface без layer violation (infrastructure → dsl запрещён).
    """

    async def before(
        self, processor_name: str, exchange: Any, context: Any
    ) -> None:
        """Выполнить операцию before процессора (метрики, трейсы, timeout)."""
        ...

    async def after(
        self,
        processor_name: str,
        exchange: Any,
        context: Any,
        error: Exception | None,
        duration_ms: float,
    ) -> None:
        """Выполнить операцию after процессора."""
        ...


__all__ = ("ProcessorMiddleware",)
