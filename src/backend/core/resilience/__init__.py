"""Resilience patterns — graceful degradation, retry, breaker, rate-limiter, bulkhead, self-healing.

Sprint 1 V16 Single-Entry: пакет образован из бывшего файла-модуля
``core/resilience.py``. Существующие импорты ``from src.backend.core.resilience
import X`` остаются валидными за счёт re-export'ов.

Структура:
- :mod:`degradation` — DegradationMode, DegradationManager, singleton
  ``degradation_manager``.
- :mod:`retry_budget` — RetryBudget + ``get_retry_budget`` + RetryBudgetExhausted.
- :mod:`bulkhead` — Bulkhead + ``get_bulkhead``.
- :mod:`self_healer` — SelfHealer + ``get_self_healer``.
- :mod:`breaker` — CircuitBreaker (alias на ``Breaker``), ``BreakerSpec``,
  ``BreakerRegistry``, ``CircuitOpen``.
- :mod:`retry` — ``RetryPolicy`` (alias ``Retry``), ``with_retry``.
- :mod:`rate_limiter` — ``RateLimit`` / ``RateLimitExceeded`` / ``RateLimiter``
  Protocol; re-export ``RedisRateLimiter`` для multi-instance use case.

Step 3.2 объединил ``infrastructure/resilience/{breaker,retry}.py`` и
``core/orchestration/retry.py`` в этот пакет; OLD-модули остаются как
backward-compat shim'ы (re-export).
"""

from __future__ import annotations

from src.backend.core.resilience.breaker import (
    Breaker,
    BreakerRegistry,
    BreakerSpec,
    CircuitBreaker,
    CircuitOpen,
    get_breaker_registry,
)
from src.backend.core.resilience.bulkhead import Bulkhead, get_bulkhead
from src.backend.core.resilience.degradation import (
    ComponentState,
    DegradationManager,
    DegradationMode,
    degradation_manager,
)
from src.backend.core.resilience.rate_limiter import (
    RateLimit,
    RateLimiter,
    RateLimitExceeded,
    RedisRateLimiter,
    get_rate_limiter,
)
from src.backend.core.resilience.retry import Retry, RetryPolicy, with_retry
from src.backend.core.resilience.retry_budget import (
    RetryBudget,
    RetryBudgetExhausted,
    get_retry_budget,
)
from src.backend.core.resilience.self_healer import SelfHealer, get_self_healer

__all__ = (
    "Breaker",
    "BreakerRegistry",
    "BreakerSpec",
    "Bulkhead",
    "CircuitBreaker",
    "CircuitOpen",
    "ComponentState",
    "DegradationManager",
    "DegradationMode",
    "RateLimit",
    "RateLimitExceeded",
    "RateLimiter",
    "RedisRateLimiter",
    "Retry",
    "RetryBudget",
    "RetryBudgetExhausted",
    "RetryPolicy",
    "SelfHealer",
    "degradation_manager",
    "get_breaker_registry",
    "get_bulkhead",
    "get_rate_limiter",
    "get_retry_budget",
    "get_self_healer",
    "with_retry",
)
