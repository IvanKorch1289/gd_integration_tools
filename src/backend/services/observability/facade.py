"""ObservabilityFacade — unified facade для metrics/tracing/logging.

S178: новый umbrella facade поверх ``core/observability/*`` модулей.
Скрывает детали реализации (metrics.py, correlation.py, baggage.py)
за единым API для extensions и DSL.

Предоставляет:
- ``record_metric()`` — Prometheus-style metric
- ``start_span()`` — distributed tracing context manager
- ``set_correlation_id()`` — request correlation
- ``log_event()`` — structured logging с correlation context

Ponytail: НЕ дублирует существующие модули. Делегирует через DI.

Использование::

    from src.backend.services.observability.facade import get_observability_facade

    facade = get_observability_facade()
    await facade.record_metric(name="orders.processed", value=1.0, tags={"status": "ok"})
    async with facade.start_span("process_order"):
        await process_order(order_id)
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from functools import lru_cache
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.utils.metrics_registry import metrics_registry

__all__ = ("ObservabilityFacade", "get_observability_facade")

_logger = get_logger("services.observability.facade")


class ObservabilityFacade:
    """Unified facade для observability concerns.

    Args:
        plugin: Имя caller'а (для metrics tag defaults).

    """

    def __init__(self, *, plugin: str = "extension") -> None:
        """Инициализация facade."""
        self._plugin = plugin

    async def record_metric(
        self, name: str, value: float = 1.0, *, tags: dict[str, str] | None = None
    ) -> None:
        """Записать metric value.

        Args:
            name: Имя metric (например, ``"orders.processed"``).
            value: Значение (counter: +1, gauge: текущее значение, histogram: latency).
            tags: Дополнительные теги (key-value).

        """
        try:
            counter = metrics_registry.counter(
                name,
                f"Observability metric {name}",
                labels=tuple({**(tags or {}), "plugin": self._plugin}),
            )
            counter.labels(**{**(tags or {}), "plugin": self._plugin}).inc(value)
        except Exception as exc:
            _logger.debug("observability.record_metric failed: %s", exc)

    @asynccontextmanager
    async def start_span(self, name: str, *, attributes: dict[str, Any] | None = None):
        """Async context manager для distributed tracing span.

        Args:
            name: Имя span (например, ``"process_order"``).
            attributes: Span attributes (key-value).

        Yields:
            Span object (или None если tracing unavailable).

        """
        try:
            from src.backend.core.observability.correlation import (
                start_span as _start_span,
            )

            with _start_span(name, attributes=attributes or {}) as span:
                yield span
        except Exception as exc:
            _logger.debug("observability.start_span failed: %s", exc)
            yield None

    def set_correlation_id(self, correlation_id: str) -> None:
        """Установить correlation_id для текущего request context.

        Args:
            correlation_id: UUID или другой уникальный идентификатор.

        """
        try:
            from src.backend.core.observability.correlation import (
                set_correlation_id as _set_cid,
            )

            _set_cid(correlation_id)
        except Exception as exc:
            _logger.debug("observability.set_correlation_id failed: %s", exc)

    def get_correlation_id(self) -> str | None:
        """Получить текущий correlation_id.

        Returns:
            Correlation ID или None.

        """
        try:
            from src.backend.core.observability.correlation import (
                get_correlation_id as _get_cid,
            )

            return _get_cid()
        except (ImportError, AttributeError, RuntimeError) as cid_exc:
            # D-A1-04 fix (cycle 33): narrow exceptions + observability.
            # Bare `except Exception` маскировал correlation_id failures
            # (отсутствующий correlation context, broken tracing backend).
            from src.backend.core.logging import get_logger

            get_logger(__name__).debug(
                "observability.correlation_id_resolve_failed",
                extra={"error": str(cid_exc)},
            )
            return None

    @contextmanager
    def log_event(
        self, event: str, *, severity: str = "info", **fields: Any
    ) -> Iterator[None]:
        """Structured logging context manager.

        Args:
            event: Имя события (например, ``"order.created"``).
            severity: ``"info"`` / ``"warning"`` / ``"error"``.
            **fields: Дополнительные structured fields.

        """
        try:
            from src.backend.core.observability.logging_helpers import (
                log_audit_event_lite,
            )

            log_audit_event_lite(_logger, severity=severity, event=event, **fields)
        except Exception as exc:
            _logger.debug("observability.log_event failed: %s", exc)
        yield


@lru_cache(maxsize=1)
def get_observability_facade() -> ObservabilityFacade:
    """Lazy singleton глобального :class:`ObservabilityFacade`."""
    return ObservabilityFacade()
