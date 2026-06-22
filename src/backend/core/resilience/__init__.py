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

# decorators.policy зависит от breaker/cache_decorators/rate_limiter/retry —
# импортируется ПОСЛЕ degradation и остальных модулей пакета, чтобы избежать
# циклической зависимости при загрузке __init__.py.
from src.backend.core.resilience.decorators import policy

# degradation ИМПОРТИРУЕТСЯ ДО decorators.policy: rate_limiter подтягивает
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
from src.backend.core.resilience.retry import Retry, RetryPolicy, with_retry
from src.backend.core.resilience.retry_budget import (
    RetryBudget,
    RetryBudgetExhausted,
    get_retry_budget,
)
from src.backend.core.resilience.self_healer import SelfHealer, get_self_healer

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
    "SelfHealer",
    "cached",
    "degradation_manager",
    "get_breaker_registry",
    "get_bulkhead",
    "get_graceful_degradation_registry",
    "get_rate_limiter",
    "get_retry_budget",
    "get_self_healer",
    "invalidate",
    "multi_cached",
    "policy",
    "with_retry",
)
