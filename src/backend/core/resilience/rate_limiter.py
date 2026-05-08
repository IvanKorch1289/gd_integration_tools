"""Унифицированный rate-limiter — single entry в `core/resilience/`.

Sprint 1 V16 Single-Entry (Step 3.2): canonical-модуль, объединяющий два
существующих механизма rate-limiting'а:

- ``infrastructure/resilience/unified_rate_limiter.py`` — Redis token-bucket
  для multi-instance-safe лимитов (используется в FastAPI middleware,
  HTTP-клиенте, webhook-handler'е). Доступен через ``RedisRateLimiter`` /
  ``get_rate_limiter()``.
- ``pyrate_limiter`` — local in-memory rate-limiter для process-level
  лимитов (singleton ``Limiter`` в ``entrypoints/dependencies/rate_limit.py``).

Этот модуль предоставляет общий тип ``RateLimit`` / ``RateLimitExceeded`` /
``RateLimiter`` Protocol-фасад. Конкретные backend'ы остаются на месте —
callsite'ы переходят на canonical-имена через миграцию (Step 3.3).

Step 3.4 добавит сюда ``BoundedInMemoryBucket`` (size-cap + LRU eviction)
и ``_pyrate_compat`` shutdown-hook helper.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# Re-export Redis-backed реализации как backward-compat. Эти классы
# по-прежнему живут в infrastructure/, потому что зависят от
# ``infrastructure.clients.storage.redis`` (cross-layer запрещён).
from src.backend.infrastructure.resilience.unified_rate_limiter import (
    RateLimit,
    RateLimitExceeded,
    RedisRateLimiter,
    get_rate_limiter,
)

__all__ = (
    "RateLimit",
    "RateLimitExceeded",
    "RateLimiter",
    "RedisRateLimiter",
    "get_rate_limiter",
)


@runtime_checkable
class RateLimiter(Protocol):
    """Единый Protocol для всех реализаций rate-limiter'а.

    Реализуется ``RedisRateLimiter`` (Redis-backed, multi-instance) и
    локальными pyrate_limiter-обёртками (in-memory). DSL-процессоры и
    middleware зависят от этого Protocol'а, что позволяет переключать
    backend без изменения callsite'ов.
    """

    async def check(self, identifier: str, policy: RateLimit) -> dict[str, Any]:
        """Проверяет/инкрементит счётчик. Бросает ``RateLimitExceeded``."""
        ...
