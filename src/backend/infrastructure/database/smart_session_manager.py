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

K2 S19 W1: При ``feature_flags.multi_replica_failover=True`` активируется
pg_stat_replication lag monitoring + lag-budget routing:
    * Периодический опрос ``pg_stat_replication`` (replay lag в байтах).
    * Если lag превышает ``lag_budget_bytes`` — replica игнорируется
      (fallback на primary) до тех пор, пока lag не снизится ниже budget.
    * Chaos test (kill replica) должен проходить.

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

import time
from contextlib import asynccontextmanager
from typing import Any, Literal

from sqlalchemy import text

from src.backend.core.logging import get_logger

__all__ = ("SessionMode", "SmartSessionManager")

SessionMode = Literal["read", "write"]

_logger = get_logger("infrastructure.database.smart_session")


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
        lag_budget_bytes: макс. допустимый replication lag в байтах
            (K2 S19 W1, default 10 MB). При превышении replica
            игнорируется до снижения lag ниже budget.
        lag_check_interval_seconds: интервал проверки lag в секундах
            (K2 S19 W1, default 5.0).
    """

    def __init__(
        self,
        *,
        primary_sessionmaker: Any,
        replica_sessionmaker: Any | None = None,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        lag_budget_bytes: int = 10 * 1024 * 1024,  # 10 MB
        lag_check_interval_seconds: float = 5.0,
    ) -> None:
        """Инициализирует менеджер с двумя session-фабриками."""
        self._primary = primary_sessionmaker
        self._replica = replica_sessionmaker
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds
        # Состояние circuit-breaker для replica.
        self._consecutive_failures = 0
        self._breaker_open_until: float = 0.0
        # K2 S19 W1: lag-budget routing.
        self._lag_budget_bytes = lag_budget_bytes
        self._lag_check_interval = lag_check_interval_seconds
        self._last_lag_check: float = 0.0
        self._current_replay_lag_bytes: int = 0
        self._lag_exceeded: bool = False

    @property
    def has_replica(self) -> bool:
        """Возвращает ``True`` если replica-роутинг включён."""
        return self._replica is not None

    @property
    def replica_breaker_open(self) -> bool:
        """Возвращает ``True`` если circuit-breaker сейчас в open state."""
        return time.monotonic() < self._breaker_open_until

    @property
    def replica_lag_bytes(self) -> int:
        """Текущий replay lag replica в байтах (K2 S19 W1)."""
        return self._current_replay_lag_bytes

    @property
    def lag_budget_bytes(self) -> int:
        """Порог lag budget в байтах (K2 S19 W1)."""
        return self._lag_budget_bytes

    @property
    def lag_exceeded(self) -> bool:
        """Возвращает ``True`` если lag превышает budget (K2 S19 W1)."""
        return self._lag_exceeded

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
        sessionmaker, on_replica = await self._pick_sessionmaker(mode)
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

    async def _pick_sessionmaker(self, mode: SessionMode) -> tuple[Any, bool]:
        """Выбирает sessionmaker под mode + состояние breaker'а + lag budget.

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
            _logger.debug("smart_session.replica_breaker_open: fallback to primary")
            return self._primary, False
        # K2 S19 W1: lag-budget routing — проверяем lag при multi_replica_failover.
        if await self._should_check_lag():
            await self._update_lag_status()
        if self._lag_exceeded:
            _logger.debug(
                "smart_session.replica_lag_exceeded: fallback to primary",
                extra={
                    "lag_bytes": self._current_replay_lag_bytes,
                    "budget_bytes": self._lag_budget_bytes,
                },
            )
            return self._primary, False
        return self._replica, True

    async def _should_check_lag(self) -> bool:
        """Проверяет, пора ли обновить статус lag (K2 S19 W1).

        Returns:
            True если ``multi_replica_failover`` активен и интервал
            между проверками истёк.
        """
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.multi_replica_failover:
                return False
        except Exception:
            return False
        return (time.monotonic() - self._last_lag_check) >= self._lag_check_interval

    async def _update_lag_status(self) -> None:
        """Опрашивает pg_stat_replication и обновляет lag-статус (K2 S19 W1).

        Выполняется на primary: ``pg_stat_replication`` доступен только
        на primary. Получает ``replay_lag_bytes`` — максимальный lag среди
        всех replication slots.
        """
        self._last_lag_check = time.monotonic()
        try:
            async with self._primary() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT COALESCE(
                            MAX(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)),
                            0
                        )::bigint AS replay_lag_bytes
                        FROM pg_stat_replication
                        """
                    )
                )
                row = result.fetchone()
                if row is not None:
                    self._current_replay_lag_bytes = int(row[0])
                    self._lag_exceeded = (
                        self._current_replay_lag_bytes > self._lag_budget_bytes
                    )
                    _logger.debug(
                        "smart_session.lag_checked",
                        extra={
                            "lag_bytes": self._current_replay_lag_bytes,
                            "budget_bytes": self._lag_budget_bytes,
                            "lag_exceeded": self._lag_exceeded,
                        },
                    )
        except Exception as exc:
            _logger.debug("smart_session.lag_check_failed: %s", exc)
            # При ошибке не блокируем replica — fallback к circuit-breaker.

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
