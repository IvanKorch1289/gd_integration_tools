"""S84 W3 — RedisLockProcessor: distributed lock guard для route.

DSL шаг ``redis_lock``: приобретает distributed Redis lock с TTL на
время выполнения route. Если lock не получен и ``fail_on_contention=True`` —
``exchange.fail()``. Иначе — pipeline идёт дальше, lock освобождается
при завершении route (через :class:`RouteBuilder` cleanup hooks).

Полезен для:
    * Одноразовых cron/ETL задач (только один инстанс).
    * Защиты от дублей в webhook retry.
    * Leader election между workers.

Пример YAML DSL::

    steps:
      - redis_lock:
          key: orders.daily_cron
          ttl_seconds: 300
          blocking_timeout: 0
          fail_on_contention: true
        output: { _lock_acquired: bool }

Пример Python DSL::

    .redis_lock(key="orders.daily_cron", ttl_seconds=300)
    .redis_lock(key="etl.backup", blocking_timeout=10.0)
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_logger = get_logger("dsl.redis_lock")


class RedisLockProcessor(BaseProcessor):
    """Distributed lock guard для route через :class:`RedisLock`.

    Args:
        key: Имя lock'а (например, ``"orders.daily_cron"``).
        ttl_seconds: TTL lock'а в секундах (default 60).
        blocking_timeout: Максимальное время ожидания lock'а
            (``0`` = non-blocking, ``None`` = бесконечно).
        fail_on_contention: Если ``True`` — при contention
            ``exchange.fail()``. Если ``False`` — pipeline идёт дальше
            (``exchange.properties["_lock_acquired"] = False``).
        key_prefix: Префикс для Redis-ключа (default ``"lock"``).
        name: Опциональное имя процессора для трассировки.

    Body contract: не используется.
    Output: ``exchange.properties["_lock_acquired"] = bool`` (всегда).
    """

    side_effect: ClassVar[Any] = "READ"
    compensatable: ClassVar[bool] = True

    def __init__(
        self,
        *,
        key: str,
        ttl_seconds: int = 60,
        blocking_timeout: float | None = None,
        fail_on_contention: bool = True,
        key_prefix: str = "lock",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"redis_lock({key})")
        self._key = key
        self._ttl = ttl_seconds
        self._blocking_timeout = blocking_timeout
        self._fail_on_contention = fail_on_contention
        self._key_prefix = key_prefix
        self._lock: Any = None  # RedisLock instance, holds active lock

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Приобретает Redis lock или fail'ит exchange."""
        try:
            from src.backend.infrastructure.clients.storage.redis_lock import RedisLock
        except ImportError as exc:
            exchange.fail(f"redis_lock: redis dependencies not installed: {exc}")
            return

        lock = RedisLock(self._key, ttl_seconds=self._ttl, key_prefix=self._key_prefix)
        try:
            acquired = await lock.acquire(blocking_timeout=self._blocking_timeout)
        except Exception as exc:  # noqa: BLE001
            _logger.exception(
                "redis_lock: acquire failed",
                extra={"key": self._key, "error": str(exc)},
            )
            exchange.fail(f"redis_lock acquire failed for {self._key!r}: {exc}")
            return

        # Всегда пишем результат в properties для downstream visibility.
        exchange.properties["_lock_acquired"] = acquired

        if not acquired:
            _logger.info(
                "redis_lock: contention detected",
                extra={"key": self._key, "ttl": self._ttl},
            )
            if self._fail_on_contention:
                exchange.fail(
                    f"redis_lock: could not acquire lock for {self._key!r} "
                    f"(ttl={self._ttl}s, blocking={self._blocking_timeout})"
                )
            return

        # Lock acquired — сохраняем ссылку для release в cleanup.
        # В текущей реализации cleanup делается через route lifecycle
        # (RouteBuilder.finalize / shutdown hooks), не здесь. Если route
        # падает, lock истечёт по TTL — self-healing semantics.
        self._lock = lock
        _logger.debug(
            "redis_lock: acquired", extra={"key": self._key, "ttl": self._ttl}
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализация в DSL: ``{redis_lock: {key, ttl_seconds, blocking_timeout, fail_on_contention, key_prefix}}``."""
        spec: dict[str, Any] = {"key": self._key, "ttl_seconds": self._ttl}
        if self._blocking_timeout is not None:
            spec["blocking_timeout"] = self._blocking_timeout
        if not self._fail_on_contention:
            spec["fail_on_contention"] = False
        if self._key_prefix != "lock":
            spec["key_prefix"] = self._key_prefix
        return {"redis_lock": spec}


__all__ = ("RedisLockProcessor",)
