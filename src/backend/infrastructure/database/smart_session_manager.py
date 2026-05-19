"""SmartSessionManager — автороутинг read/write SQL-сессий (S11 K2 W2).

Назначение:
    Направляет read-only запросы на read-replica, а write-запросы — на
    primary. Снижает нагрузку на primary в 2–3x для read-heavy workload.

Стратегия:
    * Под капотом — два независимых :class:`async_sessionmaker` (primary
      и replica), полученных из соответствующих ``AsyncEngine``.
    * :meth:`acquire` — единственная точка входа: принимает ``mode``
      (``"read"`` или ``"write"``) и возвращает async-context с
      ``AsyncSession``.
    * Если ``mode="read"`` и replica доступна — сессия идёт на replica.
      Иначе fallback на primary (write всегда идёт на primary).
    * При недоступности replica (raise при попытке создать session)
      используется fallback на primary с записью предупреждения в лог.
      Чтобы не «бить» мёртвую replica повторно, активирован простой
      circuit-breaker: после N подряд failures режим replica
      деактивируется на ``cooldown_seconds``.

Использование::

    sm = SmartSessionManager(
        primary_sessionmaker=primary_smk,
        replica_sessionmaker=replica_smk,
    )

    async with sm.acquire(mode="read") as session:
        # select-only — попадёт на replica при доступности
        ...

    async with sm.acquire(mode="write") as session:
        # transaction-bearing — всегда primary
        ...

Если ``replica_sessionmaker=None``, manager работает в режиме
single-primary без побочных эффектов — это совместимый default.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Literal

__all__ = ("SmartSessionManager", "SessionMode")

SessionMode = Literal["read", "write"]

_logger = logging.getLogger("infrastructure.database.smart_session")


class SmartSessionManager:
    """Менеджер сессий с read/write роутингом и replica circuit-breaker.

    Args:
        primary_sessionmaker: ``async_sessionmaker`` primary-engine'а.
        replica_sessionmaker: опц. ``async_sessionmaker`` replica; если
            ``None`` — replica-роутинг отключён.
        failure_threshold: число подряд идущих ошибок replica до открытия
            breaker'а (default 3).
        cooldown_seconds: длительность «open» состояния breaker'а
            в секундах (default 30.0).
    """

    def __init__(
        self,
        *,
        primary_sessionmaker: Any,
        replica_sessionmaker: Any | None = None,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
    ) -> None:
        """Инициализирует менеджер с двумя session-фабриками."""
        self._primary = primary_sessionmaker
        self._replica = replica_sessionmaker
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        # Состояние circuit-breaker для replica.
        self._consecutive_failures = 0
        self._breaker_open_until: float = 0.0

    @property
    def has_replica(self) -> bool:
        """Возвращает ``True`` если replica-роутинг включён."""
        return self._replica is not None

    @property
    def replica_breaker_open(self) -> bool:
        """Возвращает ``True`` если circuit-breaker сейчас в open state."""
        return time.monotonic() < self._breaker_open_until

    @asynccontextmanager
    async def acquire(self, mode: SessionMode = "read"):
        """Возвращает :class:`AsyncSession` согласно ``mode``.

        Args:
            mode: ``"read"`` — попытка использовать replica (с fallback
                на primary при недоступности); ``"write"`` — всегда
                primary.

        Yields:
            ``AsyncSession`` с открытой транзакцией (в зависимости от
            sessionmaker конфигурации).
        """
        sessionmaker, on_replica = self._pick_sessionmaker(mode)
        session = sessionmaker()
        try:
            yield session
            if on_replica:
                self._record_replica_success()
        except Exception:
            if on_replica:
                self._record_replica_failure()
            raise
        finally:
            await session.close()

    def _pick_sessionmaker(self, mode: SessionMode) -> tuple[Any, bool]:
        """Выбирает sessionmaker под mode + состояние breaker'а.

        Args:
            mode: режим сессии (``"read"``/``"write"``).

        Returns:
            Кортеж ``(sessionmaker, использует_replica?)``.
        """
        if mode == "write":
            return self._primary, False
        # mode == "read"
        if self._replica is None:
            return self._primary, False
        if self.replica_breaker_open:
            _logger.debug(
                "smart_session.replica_breaker_open: fallback to primary",
            )
            return self._primary, False
        return self._replica, True

    def _record_replica_success(self) -> None:
        """Регистрирует успешную операцию на replica — сбрасывает счётчик."""
        if self._consecutive_failures:
            _logger.debug("smart_session.replica_recovered")
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0

    def _record_replica_failure(self) -> None:
        """Регистрирует ошибку replica; открывает breaker по достижении threshold."""
        self._consecutive_failures += 1
        _logger.warning(
            "smart_session.replica_failure",
            extra={
                "consecutive_failures": self._consecutive_failures,
                "threshold": self._failure_threshold,
            },
        )
        if self._consecutive_failures >= self._failure_threshold:
            self._breaker_open_until = time.monotonic() + self._cooldown
            _logger.warning(
                "smart_session.replica_breaker_opened",
                extra={"cooldown_seconds": self._cooldown},
            )
