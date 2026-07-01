"""Canonical rate-limiter Protocol — единая точка входа для всех RL-контрактов.

RL_CONSOLIDATION — canonical hierarchy (4 слоя):

    Protocol (этот модуль)
      └─ RateLimiter: check(identifier, policy) -> dict[str, Any]
      └─ RateLimitChecker (core/interfaces/ratelimit_gateway.py):
         gateway-контракт check(identifier) -> tuple + check_route_override(route)
         — ДРУГОЙ контракт, не дубликат (per-route gateway, не generic limiter)
    Policy
      ├─ RateLimitPolicy (core/resilience/resilience_profile.py):
         frozen dataclass {rps, burst} — часть ResilienceProfile
      └─ RateLimiterPolicy (infrastructure/resilience/rate_limiter.py):
         dataclass {resource, limit, window_seconds} + as_rate_limit()
         — ДРУГИЕ поля, per-resource preset, не дубликат
    Implementation (infrastructure/resilience/)
      ├─ RedisRateLimiter: INCR/EXPIRE token-bucket (multi-instance)
      ├─ DistributedRedisRateLimiter: Lua EVALSHA token-bucket (Redis Cluster)
      └─ ResourceRateLimiter: facade с per-resource presets (http/grpc/kafka/...)
    Middleware
      ├─ GlobalRateLimitMiddleware (entrypoints/middlewares/global_ratelimit.py)
      └─ RateLimitMiddleware (services/execution/middlewares/rate_limit_middleware.py)

Правило: новые RL-контракты реализуют ``RateLimiter`` Protocol из этого модуля.
``RateLimiterProtocol`` в ``core/interfaces/multi_protocol.py`` — thin re-export
сюда. ``RateLimitChecker`` — отдельный gateway-контракт (другая сигнатура).

Sprint 1 V16 Single-Entry: конкретные backend'ы остаются в infrastructure/,
callsite'ы переходят на canonical-имена через ``__getattr__`` lazy-import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

def __getattr__(name: str) -> Any:
    if not TYPE_CHECKING:
        if name in (
            "RateLimit",
            "RateLimitExceeded",
            "RedisRateLimiter",
            "get_rate_limiter",
        ):
            from src.backend.core.di.providers.infrastructure_facade import (
                get_unified_rate_limiter_attr as _get_rl_attr,
            )

            return _get_rl_attr(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
