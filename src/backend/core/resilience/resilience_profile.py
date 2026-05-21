"""Unified resilience profile с per-tenant override (S13 K2 W5).

Профиль агрегирует все resilience-параметры одного логического "консумера"
внешнего сервиса — retry, circuit breaker, rate limit, bulkhead — и
позволяет хранить их в БД с per-tenant override.

Используется через :meth:`RouteBuilder.policy.retry_with_profile(name)`:
runtime lookup из :class:`ResilienceProfileStore`, fallback на global default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = (
    "BulkheadPolicy",
    "CircuitBreakerPolicy",
    "RateLimitPolicy",
    "ResilienceProfile",
    "ResilienceProfileStore",
    "RetryPolicySpec",
)


@dataclass(frozen=True, slots=True)
class RetryPolicySpec:
    """Decларативный retry-конфиг для профиля (declarative-only, без callable)."""

    max_attempts: int = 3
    base_delay_ms: int = 100
    max_delay_ms: int = 5000
    exp_base: float = 2.0
    jitter: float = 0.1


@dataclass(frozen=True, slots=True)
class CircuitBreakerPolicy:
    """Circuit breaker конфиг."""

    failure_threshold: int = 5
    recovery_timeout_s: int = 30
    half_open_max_calls: int = 3


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Token-bucket rate limit конфиг."""

    rps: int = 100
    burst: int = 20


@dataclass(frozen=True, slots=True)
class BulkheadPolicy:
    """Asyncio bulkhead — high/low watermark."""

    high_watermark: int = 100
    low_watermark: int = 50


@dataclass(frozen=True, slots=True)
class ResilienceProfile:
    """Полный профиль resilience для одного "консумера".

    Examples:
        >>> ResilienceProfile(
        ...     name="external_api_default",
        ...     retry=RetryPolicySpec(max_attempts=5),
        ...     circuit_breaker=CircuitBreakerPolicy(failure_threshold=10),
        ... )
    """

    name: str
    retry: RetryPolicySpec = field(default_factory=RetryPolicySpec)
    circuit_breaker: CircuitBreakerPolicy = field(default_factory=CircuitBreakerPolicy)
    rate_limit: RateLimitPolicy | None = None
    bulkhead: BulkheadPolicy | None = None

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResilienceProfile":
        """Восстанавливает профиль из JSONB."""
        retry_raw = payload.get("retry", {})
        cb_raw = payload.get("circuit_breaker", {})
        rl_raw = payload.get("rate_limit")
        bh_raw = payload.get("bulkhead")
        return cls(
            name=payload["name"],
            retry=RetryPolicySpec(**retry_raw) if retry_raw else RetryPolicySpec(),
            circuit_breaker=(
                CircuitBreakerPolicy(**cb_raw) if cb_raw else CircuitBreakerPolicy()
            ),
            rate_limit=RateLimitPolicy(**rl_raw) if rl_raw else None,
            bulkhead=BulkheadPolicy(**bh_raw) if bh_raw else None,
        )


class ResilienceProfileStore(Protocol):
    """Protocol для хранилищ профилей (PG / in-memory).

    Per-tenant resolution: при ``tenant_id`` ищем tenant-override → fallback
    на global default (``tenant_id is None``).
    """

    async def get(
        self, name: str, *, tenant_id: str | None = None
    ) -> ResilienceProfile | None: ...

    async def list(
        self, *, tenant_id: str | None = None
    ) -> list[ResilienceProfile]: ...

    async def upsert(
        self, profile: ResilienceProfile, *, tenant_id: str | None = None
    ) -> ResilienceProfile: ...

    async def delete(self, name: str, *, tenant_id: str | None = None) -> bool: ...
