"""Per-resource rate limiter — расширение Redis-based лимитера (ADR-005).

Использует уже существующий ``app.entrypoints.rate_limiter`` (Redis token
bucket), добавляет per-resource pre-defined policies:

* http-external — per-host limit для исходящих HTTP-запросов.
* grpc-external — per-method limit для gRPC-клиента.
* kafka-producer — per-topic limit.
* mqtt-publisher — per-topic limit.
* websocket-outbound — per-connection.

Цель — чтобы DSL-процессор мог объявить ``rate_limit(resource="http",
key="api.example.com", limit=100, window=60)`` без привязки к конкретному
Redis-клиенту.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.entrypoints.rate_limiter import RateLimit, get_rate_limiter, RateLimitExceeded

__all__ = ("RateLimiterPolicy", "ResourceRateLimiter", "RateLimitExceeded")


@dataclass(slots=True)
class RateLimiterPolicy:
    """Per-resource policy preset."""

    resource: str
    limit: int
    window_seconds: int

    def as_rate_limit(self, identifier: str) -> RateLimit:
        return RateLimit(
            limit=self.limit,
            window_seconds=self.window_seconds,
            key_prefix=f"rl:{self.resource}",
        )


class ResourceRateLimiter:
    """Фасад для Redis RL с per-resource policy presets."""

    DEFAULTS: dict[str, RateLimiterPolicy] = {
        "http": RateLimiterPolicy(resource="http", limit=100, window_seconds=60),
        "grpc": RateLimiterPolicy(resource="grpc", limit=60, window_seconds=60),
        "kafka": RateLimiterPolicy(resource="kafka", limit=500, window_seconds=60),
        "mqtt": RateLimiterPolicy(resource="mqtt", limit=200, window_seconds=60),
        "websocket": RateLimiterPolicy(resource="websocket", limit=100, window_seconds=60),
    }

    def __init__(self) -> None:
        self._presets = dict(self.DEFAULTS)

    def set_policy(self, resource: str, policy: RateLimiterPolicy) -> None:
        self._presets[resource] = policy

    async def acquire(self, resource: str, identifier: str) -> dict:
        policy = self._presets.get(resource)
        if policy is None:
            raise KeyError(f"Unknown RL resource: {resource}")
        return await get_rate_limiter().check(
            identifier=identifier,
            policy=policy.as_rate_limit(identifier),
        )
