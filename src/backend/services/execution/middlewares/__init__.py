"""Встроенные middleware для :class:`DefaultActionDispatcher` (W14.1.C).

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

from src.services.execution.middlewares.audit_middleware import AuditMiddleware
from src.services.execution.middlewares.idempotency_middleware import (
    IdempotencyMiddleware,
)
from src.services.execution.middlewares.rate_limit_middleware import RateLimitMiddleware

__all__ = ("AuditMiddleware", "IdempotencyMiddleware", "RateLimitMiddleware")
