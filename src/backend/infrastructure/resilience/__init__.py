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

from src.backend.core.resilience.retry_budget import RetryBudget  # noqa: F401 — re-export
from src.backend.infrastructure.resilience.bulkhead import Bulkhead, BulkheadRegistry  # noqa: F401 — re-export
from src.backend.infrastructure.resilience.health import (
    build_resilience_health_check,
    register_resilience_health_checks,
    resilience_components_report,
)
from src.backend.infrastructure.resilience.time_limiter import TimeLimiter  # noqa: F401 — re-export
from src.backend.infrastructure.resilience.unified_rate_limiter import (
    RateLimiterPolicy,
    ResourceRateLimiter,
)

__all__ = (
    "Bulkhead",
    "BulkheadRegistry",
    "RateLimiterPolicy",
    "ResourceRateLimiter",
    "RetryBudget",
    "TimeLimiter",
    "build_resilience_health_check",
    "register_resilience_health_checks",
    "resilience_components_report",
)
