"""Resilience patterns — graceful degradation, retry, breaker, rate-limiter, bulkhead.

Sprint 1 V16 Single-Entry: пакет образован из бывшего файла-модуля
``core/resilience.py``. Существующие импорты ``from src.backend.core.resilience
import X`` остаются валидными за счёт re-export'ов.

Структура:
- :mod:`degradation` — DegradationMode, DegradationManager, singleton
  ``degradation_manager``.
- :mod:`retry_budget` — RetryBudget + ``get_retry_budget`` + RetryBudgetExhausted.
- :mod:`bulkhead` — Bulkhead + ``get_bulkhead``.
- :mod:`breaker` — CircuitBreaker (alias на ``Breaker``), ``BreakerSpec``,
  ``BreakerRegistry``, ``CircuitOpen``.
- :mod:`circuit_breaker` — ``CircuitBreakerSpec``, ``SlidingWindowBreaker``,
  ``ReplicaFailoverBreaker``, ``BreakerLike``. Re-export canonical API.
  Интегрировано в smart_session_manager через ``_breaker_facade``.
- :mod:`retry` — ``RetryPolicy`` (alias ``Retry``), ``with_retry``.
- :mod:`rate_limiter` — ``RateLimit`` / ``RateLimitExceeded`` / ``RateLimiter``
  Protocol; re-export ``RedisRateLimiter`` для multi-instance use case.
  Канонический низкоуровневый API (``check(identifier, policy) -> dict``).
- :mod:`unified_rate_limiter` — high-level facade ``UnifiedRateLimiter`` +
  typed ``RateLimitResult`` dataclass. Используется только DI-wiring
  (``core/di/providers/infrastructure_locator``, ``resilience_bridge``)
  и unit-тестами; намеренно НЕ re-exported в ``__all__`` чтобы DSL
  callsite'ы зависели от канонического ``RateLimiter`` Protocol, а не
  от typed-фасада (разные слои абстракции, не дубликаты).

Step 3.2 объединил ``infrastructure/resilience/{breaker,retry}.py`` и
``core/orchestration/retry.py`` в этот пакет; OLD-модули остаются как
backward-compat shim'ы (re-export).
"""

from __future__ import annotations as annotations

from src.backend.core.resilience.adaptive_timeout import (
    AdaptiveTimeoutConfig,
    AdaptiveTimeoutPolicy,
)
from src.backend.core.resilience.breaker import (
    Breaker,
    BreakerRegistry,
    BreakerSpec,
    CircuitBreaker,
    CircuitOpen,
    get_breaker_registry,
)
from src.backend.core.resilience.cache_decorators import (
    cached,
    invalidate,
    multi_cached,
)

# degradation ИМПОРТИРУЕТСЯ ДО остальных: rate_limiter подтягивает
# infrastructure/resilience/__init__.py → coordinator.py, который делает
# обратный импорт ``from src.backend.core.resilience import DegradationManager``.
# Если этот блок окажется НИЖЕ decorators, поднимется циклическая
# ImportError (blocker b1 Sprint 17 W1).
from src.backend.core.resilience.degradation import (
    ComponentState,
    DegradationManager,
    DegradationMode,
    degradation_manager,
)
from src.backend.core.resilience.graceful_degradation import (
    DegradationFeature,
    FeatureState,
    GracefulDegradationRegistry,
    get_graceful_degradation_registry,
)
from src.backend.core.resilience.rate_limiter import (
    RateLimit,
    RateLimiter,
    RateLimitExceeded,
    RedisRateLimiter,
    get_rate_limiter,
)
from src.backend.core.resilience.retry import (
    Retry,
    RetryPolicy,
    async_retry,
    default_retryable,
    make_async_retry,
    retry_async,
    with_retry,
)
from src.backend.core.resilience.retry_budget import (
    RetryBudget,
    RetryBudgetExhausted,
    get_retry_budget,
)

__all__ = (
    "AdaptiveTimeoutConfig",
    "AdaptiveTimeoutPolicy",
    "Breaker",
    "BreakerRegistry",
    "BreakerSpec",
    "Bulkhead",
    "CircuitBreaker",
    "CircuitOpen",
    "ComponentState",
    "DegradationFeature",
    "DegradationManager",
    "DegradationMode",
    "FeatureState",
    "GracefulDegradationRegistry",
    "RateLimit",
    "RateLimitExceeded",
    "RateLimiter",
    "RedisRateLimiter",
    "Retry",
    "RetryBudget",
    "RetryBudgetExhausted",
    "RetryPolicy",
    "async_retry",
    "cached",
    "default_retryable",
    "degradation_manager",
    "get_breaker_registry",
    "get_bulkhead",
    "get_graceful_degradation_registry",
    "get_rate_limiter",
    "get_retry_budget",
    "invalidate",
    "make_async_retry",
    "multi_cached",
    "retry_async",
    "with_retry",
)
