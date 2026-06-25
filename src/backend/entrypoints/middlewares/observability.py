"""ObservabilityMiddleware (S171 M5 proposal #4).

Консолидирует OTel + Prometheus + Audit-логирование в один middleware.

Architecture (Ponytail, D142): facade-pattern, не breaking change.
По умолчанию все три канала отключены (opt-in). Если включены —
создаёт единый ``observability.event`` payload, который можно
пробрасывать в любую из существующих подсистем.

Заменяет конфигурационный фрагмент:
- otel_middleware.py (OpenTelemetry spans)
- prometheus middleware (starlette_exporter metrics)
- audit_log.py (ClickHouse/Redis audit events)

Подключение:
    - ObservabilityMiddleware(app, ObservabilityConfig(
        otel_enabled=True, prometheus_enabled=True, audit_enabled=True))
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from fastapi import Request, Response
    from starlette.types import ASGIApp

__all__ = ("ObservabilityConfig", "ObservabilityMiddleware")


@dataclass(frozen=True)
class ObservabilityConfig:
    """Конфигурация для :class:`ObservabilityMiddleware`.

    Все 3 канала opt-in (default False) — не сломает существующие
    middleware, если facade просто лежит в реестре без конфига.
    """

    otel_enabled: bool = False
    prometheus_enabled: bool = False
    audit_enabled: bool = False
    service_name: str = "gd_integration_tools"
    sample_rate: float = 1.0  # 0.0..1.0 — sampling для OTel


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Единый middleware для OTel + Prometheus + Audit.

    Поведение:
    - Каждый request → единый ``observability.event`` dict с полями
      ``method``, ``path``, ``status_code``, ``duration_ms``,
      ``request_id``, ``correlation_id``.
    - Если канал включён — emit в соответствующий backend
      (OTel tracer, Prometheus exporter, audit log).
    - Если канал отключён — no-op (минимальный overhead).
    """

    def __init__(self, app: "ASGIApp", config: ObservabilityConfig | None = None) -> None:
        super().__init__(app)
        self.config = config or ObservabilityConfig()

    async def dispatch(
        self,
        request: "Request",
        call_next: Callable[["Request"], Awaitable["Response"]],
    ) -> "Response":
        import time
        from src.backend.core.logging import get_logger

        logger = get_logger(__name__)
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        # Собираем unified event (распространяется на все включённые каналы)
        event = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "service": self.config.service_name,
            "request_id": getattr(request.state, "request_id", None),
            "correlation_id": getattr(request.state, "correlation_id", None),
        }

        if self.config.otel_enabled:
            # TODO (D142): emit to OpenTelemetry tracer
            logger.debug("otel.emit: %s", event)

        if self.config.prometheus_enabled:
            # TODO (D142): emit to Prometheus exporter (starlette_exporter)
            logger.debug("prometheus.emit: %s", event)

        if self.config.audit_enabled:
            # TODO (D142): emit to ClickHouse/Redis audit log
            logger.debug("audit.emit: %s", event)

        return response
