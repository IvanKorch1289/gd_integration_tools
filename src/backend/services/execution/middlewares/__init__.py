"""Встроенные middleware для :class:`DefaultActionDispatcher` (W14.1.C).

См. ADR-0062 (Sprint 9 K5 W7): этот пакет работает с типизированным
``DispatchContext`` — не путать с
:mod:`src.backend.entrypoints.middlewares` (pure ASGI HTTP-layer).

Состав:

* :class:`AuditMiddleware` — логирует факт вызова action (action_id,
  correlation_id, success, duration_ms) через ``app_logger``.
* :class:`IdempotencyMiddleware` — кэш по
  :attr:`DispatchContext.idempotency_key`; baseline — in-memory dict,
  Redis-backed заменяется через DI позднее.
* :class:`RateLimitMiddleware` — применяет
  :attr:`ActionMetadata.rate_limit` через
  ``infrastructure.resilience.unified_rate_limiter`` (lazy-resolved).

Все middleware — no-op, если их параметры в ``metadata`` или ``context``
не заданы.
"""

from src.backend.services.execution.middlewares.audit_middleware import AuditMiddleware
from src.backend.services.execution.middlewares.idempotency_middleware import (
    IdempotencyMiddleware,
)
from src.backend.services.execution.middlewares.rate_limit_middleware import (
    RateLimitMiddleware,
)

__all__ = ("AuditMiddleware", "IdempotencyMiddleware", "RateLimitMiddleware")
