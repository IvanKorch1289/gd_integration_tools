"""ResilienceFacade — capability-checked фасад для resilience patterns.

Provides capability-checked access to circuit breaker, rate limiter,
bulkhead, and retry for extensions and DSL processors.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.logging import get_logger
from src.backend.core.observability.logging_helpers import log_audit_event_lite

__all__ = ("ResilienceFacade",)

_logger = get_logger("services.resilience.facade")


class ResilienceFacade:
    """Capability-checked фасад для resilience patterns.

    Args:
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
    """

    def __init__(
        self, *, capability_check: Any | None = None, plugin: str = "extension"
    ) -> None:
        self._check = capability_check
        self._plugin = plugin

    def _assert(self, action: str, resource: str) -> None:
        if self._check is not None:
            self._check(self._plugin, action, resource)

    async def check_rate_limit(
        self, identifier: str, limit: int, window_seconds: float
    ) -> bool:
        """Проверить rate limit для идентификатора.

        Args:
            identifier: Уникальный ключ (tenant_id/client_ip).
            limit: Максимум запросов в окне.
            window_seconds: Размер окна в секундах.

        Returns:
            True если разрешено, False если превышен лимит.
        """
        self._assert("resilience.rate_limit", identifier)
        try:
            from src.backend.core.resilience import RateLimit, get_rate_limiter

            limiter = get_rate_limiter()
            policy = RateLimit(limit=limit, window_seconds=window_seconds)
            result = await limiter.check(identifier, policy)
            return result.get("allowed", True)
        except Exception as exc:
            # S175 M10.1: structured log (audit-event-type field)
            # — observability через structlog/OTel pipeline.
            log_audit_event_lite(
                _logger,
                severity="warning",
                event="resilience.rate_limit.check_failed",
                message=f"Rate limit check failed: {exc}",
                identifier=identifier,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return True  # Fail-open for rate limiting

    def get_breaker(self, name: str) -> Any:
        """Получить circuit breaker по имени.

        Args:
            name: Имя breaker'а (e.g., "redis", "http_upstream").

        Returns:
            Breaker instance.
        """
        self._assert("resilience.breaker", name)
        try:
            from src.backend.core.resilience import get_breaker_registry

            registry = get_breaker_registry()
            return registry.get_or_create(name)
        except Exception as exc:
            # S175 M10.1: structured log (audit-event-type field).
            log_audit_event_lite(
                _logger,
                severity="warning",
                event="resilience.breaker.get_failed",
                message=f"Failed to get breaker {name}: {exc}",
                breaker_name=name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise ServiceError(f"Failed to get breaker: {exc}") from exc
