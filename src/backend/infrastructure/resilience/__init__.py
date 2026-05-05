"""Resilience package — bulkhead, time limiter, rate limiter, retry budget.

Единый источник правды для resilience-паттернов (ADR-005).

Публичный API::

    from src.backend.infrastructure.resilience import (
        Bulkhead,
        TimeLimiter,
        RetryBudget,
        RateLimiterPolicy,
    )

См. отдельные модули для деталей.
"""

from src.backend.infrastructure.resilience.bulkhead import Bulkhead, BulkheadRegistry
from src.backend.infrastructure.resilience.coordinator import (
    ComponentStatus,
    ResilienceCoordinator,
    get_resilience_coordinator,
    set_resilience_coordinator,
)
from src.backend.infrastructure.resilience.health import (
    build_resilience_health_check,
    register_resilience_health_checks,
    resilience_components_report,
)
from src.backend.infrastructure.resilience.rate_limiter import (
    RateLimiterPolicy,
    ResourceRateLimiter,
)
from src.backend.infrastructure.resilience.retry_budget import RetryBudget
from src.backend.infrastructure.resilience.time_limiter import TimeLimiter

__all__ = (
    "Bulkhead",
    "BulkheadRegistry",
    "ComponentStatus",
    "ResilienceCoordinator",
    "TimeLimiter",
    "RetryBudget",
    "RateLimiterPolicy",
    "ResourceRateLimiter",
    "build_resilience_health_check",
    "get_resilience_coordinator",
    "register_resilience_health_checks",
    "resilience_components_report",
    "set_resilience_coordinator",
)
