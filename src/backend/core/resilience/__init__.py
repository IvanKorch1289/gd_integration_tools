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

Примечание (D-AUDIT-9601 follow-up): ранее существовавший
``unified_rate_limiter.py`` (``UnifiedRateLimiter`` + ``RateLimitResult``)
удалён в 2026-08-12 — facade scaffold (S174) не имел production callsites,
содержал fail-OPEN fallback при ошибке DI (``allowed=True`` при
Exception), что является security risk. DSL/extensions продолжают
использовать канонический ``RateLimiter`` Protocol через
``infrastructure.resilience.unified_rate_limiter``.

Step 3.2 объединил ``infrastructure/resilience/{breaker,retry}.py`` и
``core/orchestration/retry.py`` в этот пакет; OLD-модули остаются как
backward-compat shim'ы (re-export).

Ленивый re-export (PEP 562)
---------------------------
``__init__`` пакета **не импортирует** подмодули на старте: каждый
публичный символ резолвится по первому обращению (см. ``_LAZY_EXPORTS``
и ``__getattr__``). Причина — циклический импорт между слоями
core/infrastructure, который на Python 3.14 приводил к взаимоблокировке
импортов и тихой потере событий аудита (детали в комментарии к
``_LAZY_EXPORTS``).

``Bulkhead``/``get_bulkhead`` намеренно **не** входят в публичный API
core: каноническое место — ``src.backend.infrastructure.resilience.bulkhead``
(core не импортирует infrastructure).

"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — только для статического анализа (mypy)
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

#: Имя символа → подмодуль пакета. Ленивый re-export (PEP 562).
#:
#: Почему лениво, а не eager-импорты (волна 36, локализация KNOWN-01):
#: eager-``__init__`` создавал ЦИКЛИЧЕСКИЙ ИМПОРТ:
#:
#:   core.resilience.__init__ → core.resilience.rate_limiter
#:     → infrastructure.resilience.unified_rate_limiter → infrastructure.resilience.__init__
#:       → coordinator → ``from src.backend.core.resilience import DegradationManager``
#:
#: Раньше цикл разрывался ПОРЯДКОМ блоков в ``__init__`` (degradation выше
#: rate_limiter) — хрупкая договорённость. На Python 3.14 с per-module
#: импорт-локом прямой импорт подмодуля (``from
#: src.backend.core.resilience.retry import retry_async`` — так делает
#: clickhouse-аудит) приводил к ``_DeadlockError: deadlock detected by
#: _ModuleLock('src.backend.core.resilience.retry')``. Ошибка глушилась
#: ``emit_audit_safe`` → **события аудита терялись безвозвратно**, а пакет
#: оставался удалённым из ``sys.modules`` → следующий импорт падал с
#: ``KeyError: 'src.backend.core.resilience'``.
#:
#: Ленивый re-export убирает сам класс дефекта: ``__init__`` не импортирует
#: подмодули на старте, поэтому ре-ентрантность невозможна.
_LAZY_EXPORTS: dict[str, str] = {
    "AdaptiveTimeoutConfig": "adaptive_timeout",
    "AdaptiveTimeoutPolicy": "adaptive_timeout",
    "Breaker": "breaker",
    "BreakerRegistry": "breaker",
    "BreakerSpec": "breaker",
    "CircuitBreaker": "breaker",
    "CircuitOpen": "breaker",
    "get_breaker_registry": "breaker",
    "cached": "cache_decorators",
    "invalidate": "cache_decorators",
    "multi_cached": "cache_decorators",
    "ComponentState": "degradation",
    "DegradationManager": "degradation",
    "DegradationMode": "degradation",
    "degradation_manager": "degradation",
    "DegradationFeature": "graceful_degradation",
    "FeatureState": "graceful_degradation",
    "GracefulDegradationRegistry": "graceful_degradation",
    "get_graceful_degradation_registry": "graceful_degradation",
    "RateLimit": "rate_limiter",
    "RateLimiter": "rate_limiter",
    "RateLimitExceeded": "rate_limiter",
    "RedisRateLimiter": "rate_limiter",
    "get_rate_limiter": "rate_limiter",
    "Retry": "retry",
    "RetryPolicy": "retry",
    "async_retry": "retry",
    "default_retryable": "retry",
    "make_async_retry": "retry",
    "retry_async": "retry",
    "with_retry": "retry",
    "RetryBudget": "retry_budget",
    "RetryBudgetExhausted": "retry_budget",
    "get_retry_budget": "retry_budget",
}


def __getattr__(name: str) -> Any:
    """Ленивый re-export публичного API пакета (PEP 562).

    Args:
        name: Имя экспортируемого символа.

    Returns:
        Объект из соответствующего подмодуля пакета.

    Raises:
        AttributeError: Символ не входит в публичный API пакета.

    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Список публичных символов пакета (для автодополнения)."""
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


__all__ = (
    "AdaptiveTimeoutConfig",
    "AdaptiveTimeoutPolicy",
    "Breaker",
    "BreakerRegistry",
    "BreakerSpec",
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
    "get_graceful_degradation_registry",
    "get_rate_limiter",
    "get_retry_budget",
    "invalidate",
    "make_async_retry",
    "multi_cached",
    "retry_async",
    "with_retry",
)
