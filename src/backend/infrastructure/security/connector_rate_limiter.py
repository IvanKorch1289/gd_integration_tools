"""Per-connector rate limiter (Security Wave S1).

Унифицированный rate-limit для всех не-HTTP коннекторов (sources, sinks,
storage). Каждый connector регистрирует свой bucket при первом использовании,
либо использует :data:`DEFAULT_POLICY` (100 req/s).

Built on top of :class:`RedisRateLimiter` (fixed-window, multi-instance safe).
Без Redis (или при сбое) — fail-open (запрос пропускается), чтобы
не ломать прод при падении rate-limiter сервиса.

Usage::

    limiter = get_connector_rate_limiter()
    await limiter.check("kafka_publisher_main")
    await limiter.check("http_sink", scope="tenant_42")

Deviation note (S1):
    Реальный :class:`unified_rate_limiter.RateLimit` — fixed-window
    (``limit, window_seconds``), не token-bucket. Поэтому ``burst`` в
    :meth:`register` — advisory metadata (для observability), не активный
    параметр. Если потребуется честный burst — переходим на token-bucket
    бэкенд (Redis Lua / Sliding-Window); см. ROADMAP R7.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.infrastructure.resilience.unified_rate_limiter import (
    RateLimit,
    RateLimitExceeded,
    get_rate_limiter,
)

__all__ = (
    "ConnectorRateLimiter",
    "RateLimitExceeded",
    "get_connector_rate_limiter",
)

logger = get_logger("security.connector_rl")


_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\w+)\s*$")
_RATE_UNITS_S = {
    "s": 1, "sec": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "minute": 60, "minutes": 60,
}


def _parse_rate(rate: str) -> tuple[int, int]:
    """Parse ``"<N>/<unit>"`` → ``(limit, window_seconds)``.

    Поддерживает ``/s`` и ``/m`` (по аналогии с nginx ``limit_req``).
    При ошибке парсинга — возвращает ``(100, 1)`` (default fallback).

    Examples:
        >>> _parse_rate("200/s")
        (200, 1)
        >>> _parse_rate("5/min")
        (5, 60)

    """
    m = _RATE_RE.match(rate)
    if m is None:
        logger.warning("Unknown rate format %r, fallback to 100/1s", rate)
        return 100, 1
    limit = int(m.group(1))
    unit = m.group(2).lower()
    seconds = _RATE_UNITS_S.get(unit)
    if seconds is None:
        logger.warning("Unknown rate unit %r, fallback to 1s", unit)
        seconds = 1
    return limit, seconds


class ConnectorRateLimiter:
    """Per-connector rate limiter (fixed-window через RedisRateLimiter).

    Регистрирует политику :meth:`register` для каждого коннектора; при
    отсутствии записи — используется :data:`DEFAULT_POLICY`.

    Каждый вызов :meth:`check` делегирует в :func:`get_rate_limiter`
    (singleton ``RedisRateLimiter``). При падении Redis — fail-open
    (запрос пропускается, warning в логе).
    """

    DEFAULT_RATE = "100/s"
    DEFAULT_BURST = 100

    def __init__(self) -> None:
        self._policies: dict[str, tuple[str, int, int]] = {}  # name → (rate, burst, window_seconds)
        self._lock = asyncio.Lock()

    def register(self, connector_name: str, rate: str, burst: int) -> None:
        """Регистрирует политику rate-limit для коннектора.

        Args:
            connector_name: Стабильный идентификатор (например,
                ``"kafka_publisher_main"`` или ``"http_sink"``).
            rate: Строковый rate (``"200/s"``, ``"5/min"``).
            burst: Advisory burst size (max in-flight). Реальный
                limiter — fixed-window, burst не дросселирует; параметр
                сохранён для observability и обратной совместимости с
                будущим token-bucket бэкендом.

        """
        _limit, window = _parse_rate(rate)
        self._policies[connector_name] = (rate, burst, window)
        logger.debug(
            "Connector RL registered: %s rate=%s burst=%d window=%ds",
            connector_name, rate, burst, window,
        )

    def _resolve(self, connector_name: str) -> tuple[str, int, int]:
        """Возвращает ``(rate_str, burst, window_seconds)`` для коннектора."""
        if connector_name in self._policies:
            return self._policies[connector_name]
        return (self.DEFAULT_RATE, self.DEFAULT_BURST, 1)

    async def check(
        self,
        connector_name: str,
        *,
        scope: str | None = None,
    ) -> None:
        """Проверяет rate-limit для коннектора.

        Args:
            connector_name: Идентификатор коннектора.
            scope: Опциональный scope (tenant_id, topic, ...), добавляется
                к Redis-ключу для изоляции.

        Raises:
            RateLimitExceeded: Если лимит превышен.

        """
        rate_str, _burst, window = self._resolve(connector_name)
        limit, _ = _parse_rate(rate_str)
        key = f"{connector_name}:{scope}" if scope else connector_name
        policy = RateLimit(
            limit=limit,
            window_seconds=window,
            key_prefix="connrl",
            tenant_aware=False,
        )
        try:
            await get_rate_limiter().check(identifier=key, policy=policy)
        except RateLimitExceeded:
            logger.warning(
                "Connector RL exceeded: %s (scope=%s, limit=%d/%ds)",
                connector_name, scope or "-", limit, window,
            )
            raise

    async def with_limit(
        self,
        connector_name: str,
        func: Callable[..., Awaitable[Any]],
        *args: Any,
        scope: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Обёртка: rate-limit + invoke корутину.

        Args:
            connector_name: Идентификатор коннектора.
            func: Async callable для выполнения.
            *args, **kwargs: Аргументы для ``func``.
            scope: Опциональный scope.

        Returns:
            Результат ``func(*args, **kwargs)``.

        """
        await self.check(connector_name, scope=scope)
        return await func(*args, **kwargs)


_instance: ConnectorRateLimiter | None = None


def get_connector_rate_limiter() -> ConnectorRateLimiter:
    """Singleton-фасад для :class:`ConnectorRateLimiter`."""
    global _instance
    if _instance is None:
        _instance = ConnectorRateLimiter()
    return _instance
