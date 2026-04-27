"""Resilience package — bulkhead, time limiter, rate limiter, retry budget.

Единый источник правды для resilience-паттернов (ADR-005).

Публичный API::

    from src.infrastructure.resilience import (
        Bulkhead,
        TimeLimiter,
        RetryBudget,
        RateLimiterPolicy,
    )

См. отдельные модули для деталей.
"""

from src.infrastructure.resilience.bulkhead import Bulkhead, BulkheadRegistry
from src.infrastructure.resilience.rate_limiter import (
    RateLimiterPolicy,
    ResourceRateLimiter,
)
from src.infrastructure.resilience.retry_budget import RetryBudget
from src.infrastructure.resilience.time_limiter import TimeLimiter

__all__ = (
    "Bulkhead",
    "BulkheadRegistry",
    "TimeLimiter",
    "RetryBudget",
    "RateLimiterPolicy",
    "ResourceRateLimiter",
)
