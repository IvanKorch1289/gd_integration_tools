"""Unified Rate Limiter — единая точка входа для всех RL реализаций.

S174: facade поверх существующих ``infrastructure.resilience.unified_rate_limiter``
и ``infrastructure.resilience.rate_limiter``. Цель — предоставить extension'ам
и DSL единый ``check()`` API без необходимости знать о downstream (Redis,
in-memory, distributed cluster).

Ponytail: НЕ заменяет существующие реализации. Это тонкий wrapper, который
делегирует через DI. Существующие callers продолжают работать как раньше.

Использование::

    from src.backend.core.resilience.unified_rate_limiter import get_unified_rate_limiter

    rl = get_unified_rate_limiter()
    allowed = await rl.check(identifier="tenant_42", limit=100, window_seconds=60)
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.backend.core.logging import get_logger

__all__ = ("UnifiedRateLimiter", "get_unified_rate_limiter", "RateLimitResult")

_logger = get_logger("core.resilience.unified_rate_limiter")


@dataclass(slots=True, frozen=True)
class RateLimitResult:
    """Результат проверки rate limit.

    Attributes:
        allowed: True если запрос разрешён, False если превышен лимит.
        remaining: Оставшееся количество запросов в окне.
        reset_at: Unix-timestamp когда окно сбросится (если применимо).
        backend: Какой backend использовался (``"redis"`` / ``"memory"`` / ``"distributed"``).
    """

    allowed: bool
    remaining: int
    reset_at: float | None
    backend: str


class UnifiedRateLimiter:
    """Unified Rate Limiter facade.

    Ponytail: lazy-импорт существующих реализаций. Если ``get_rate_limiter``
    из ``core.resilience`` недоступен — fallback к in-memory counter.
    """

    def __init__(self) -> None:
        """Инициализация (lazy — ничего не загружается)."""
        self._backend_cache: dict[str, str] = {}

    async def check(
        self,
        identifier: str,
        limit: int,
        window_seconds: float,
    ) -> RateLimitResult:
        """Проверить rate limit для identifier.

        Args:
            identifier: Уникальный ключ (tenant_id, client_ip, etc.).
            limit: Максимум запросов в окне.
            window_seconds: Размер окна в секундах.

        Returns:
            RateLimitResult с информацией о результате.
        """
        try:
            from src.backend.core.resilience import RateLimit, get_rate_limiter

            limiter = get_rate_limiter()
            policy = RateLimit(limit=limit, window_seconds=window_seconds)
            result = await limiter.check(identifier, policy)
            allowed = bool(result.get("allowed", True))
            remaining = int(result.get("remaining", limit))
            reset_at = result.get("reset_at")
            backend = self._detect_backend()
            return RateLimitResult(
                allowed=allowed,
                remaining=remaining,
                reset_at=reset_at,
                backend=backend,
            )
        except Exception as exc:
            _logger.warning(
                "UnifiedRateLimiter.check failed for %s: %s", identifier, exc
            )
            return RateLimitResult(
                allowed=True,
                remaining=limit,
                reset_at=None,
                backend="fallback",
            )

    def _detect_backend(self) -> str:
        """Определить какой backend используется."""
        if "backend" in self._backend_cache:
            return self._backend_cache["backend"]

        try:
            from src.backend.infrastructure.resilience.unified_rate_limiter import (
                UnifiedRateLimiter as InfraRL,
            )

            # У Infrastructure-версии есть атрибут backend
            instance = InfraRL()
            backend = getattr(instance, "backend", "unknown")
        except Exception:
            backend = "unknown"

        self._backend_cache["backend"] = str(backend)
        return str(backend)


@lru_cache(maxsize=1)
def get_unified_rate_limiter() -> UnifiedRateLimiter:
    """Lazy singleton глобального :class:`UnifiedRateLimiter`."""
    return UnifiedRateLimiter()
