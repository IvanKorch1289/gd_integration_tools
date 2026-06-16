"""RateLimitGateway — Protocol и конфигурация для rate-limiting.

Canonical location для RateLimitChecker Protocol и RateLimitConfig.
Entrypoints импортирует отсюда, а не наоборот.

Использование в расширениях:
    from src.backend.core.interfaces.ratelimit_gateway import RateLimitChecker
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ("RateLimitChecker", "RateLimitConfig", "RateLimitGateway")


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Per-route rate-limit configuration.

    Attributes:
        max_per_window: Maximum requests allowed per window.
        window_seconds: Duration of the rate-limit window in seconds.
    """

    max_per_window: int
    window_seconds: float


@runtime_checkable
class RateLimitChecker(Protocol):
    """Контракт rate-limit-проверки.

    Entrypoint implementations (FakeRateLimitChecker, RedisRateLimitChecker)
    implement this Protocol. Extensions depend on this Protocol, not on
    concrete implementations.
    """

    async def check(self, identifier: str) -> tuple[bool, int, int]:
        """Проверить лимит для идентификатора.

        Args:
            identifier: Уникальный ключ (tenant_id/client_ip/correlation_id).

        Returns:
            (allowed, remaining, retry_after_seconds). Если allowed=False —
            ``retry_after_seconds`` указывает через сколько сек повторить.
        """

    async def check_route_override(self, route: str) -> RateLimitConfig | None:
        """Возвращает per-route override для заданного route.

        Args:
            route: The route path to check for override.

        Returns:
            :class:`RateLimitConfig` если есть override для route,
            иначе ``None``.
        """


# Public alias following gateway naming convention
RateLimitGateway = RateLimitChecker
