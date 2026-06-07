"""ConnectionReuseManager — idle ping + reuse-on-demand для backend pools.

Назначение:
    Дополнительный слой поверх существующих connection pools (V15 R-V15-14).
    Отслеживает метаданные каждого connection (created_at, last_used, use_count),
    перед возвратом connection из pool проверяет:

    - если время жизни connection превысило ``max_lifetime_seconds`` — пересоздаёт
      connection через повторный acquire из pool (auto-recycle);
    - если connection простаивал дольше ``idle_timeout_seconds`` — выполняет
      ping-callable для проверки «живости» до возврата вызывающему коду.

    Активируется только при включённом feature-flag ``connection_reuse_manager``
    (default-OFF). При выключенном флаге ``acquire`` немедленно возвращает
    connection из pool без дополнительных проверок.

Использование::

    manager = get_connection_reuse_manager()
    manager.register_pool(
        name="db_main",
        pool=engine.pool,
        ping_callable=ping_db,
        max_lifetime_seconds=3600.0,
        idle_timeout_seconds=60.0,
    )

    conn = await manager.acquire("db_main")
    try:
        ...
    finally:
        await manager.release("db_main", conn)

Архитектура:
    Singleton ``get_connection_reuse_manager()`` — один экземпляр на процесс.
    Не создаёт background-задач — проверки выполняются синхронно в ``acquire``.
    Совместим с ``PoolHealthMonitor`` из ``pool_health.py`` (разные уровни).
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = (
    "ConnectionMetadata",
    "ConnectionReuseManager",
    "PoolRegistration",
    "get_connection_reuse_manager",
)

logger = get_logger("infrastructure.clients.connection_reuse")


# ---------------------------------------------------------------------------
# Вспомогательные dataclass'ы
# ---------------------------------------------------------------------------


@dataclass
class ConnectionMetadata:
    """Метаданные одного connection в рамках pool-записи.

    Attributes:
        name: Логическое имя pool, к которому принадлежит connection.
        created_at: Время создания connection (monotonic-секунды).
        last_used: Время последнего использования connection (monotonic-секунды).
        use_count: Счётчик успешных acquire для этого connection.
    """

    name: str
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    use_count: int = 0


@dataclass
class PoolRegistration:
    """Запись о зарегистрированном pool с его политиками reuse.

    Attributes:
        name: Логическое имя pool (уникальный ключ).
        pool: Объект pool (любой тип); используется для повторного acquire
            при auto-recycle.
        ping_callable: Async-callable (pool: Any) → Any; принимает pool-объект,
            проверяет «живость» backend и возвращает любое значение.
        max_lifetime_seconds: Максимальное время жизни connection (сек).
            По умолчанию 3600 (1 час).
        idle_timeout_seconds: Порог простоя (сек) перед ping.
            По умолчанию 60 секунд.
        last_connection: Текущий «активный» connection (если был acquire).
        metadata: Метаданные текущего connection (или None до первого acquire).
    """

    name: str
    pool: Any
    ping_callable: Callable[[Any], Awaitable[Any]]
    max_lifetime_seconds: float = 3600.0
    idle_timeout_seconds: float = 60.0
    last_connection: Any = field(default=None, compare=False)
    metadata: ConnectionMetadata | None = field(default=None, compare=False)


# ---------------------------------------------------------------------------
# Основной менеджер
# ---------------------------------------------------------------------------


class ConnectionReuseManager:
    """Менеджер повторного использования connections поверх backend pools.

    Реализует паттерн «reuse-on-demand» (V15 R-V15-14):
    перед возвратом connection проверяет его lifetime и idle-период.
    При необходимости выполняет ping или пересоздаёт connection.

    Default-OFF через ``feature_flags.connection_reuse_manager``.
    При отключённом флаге ``acquire`` немедленно возвращает pool-объект
    без каких-либо проверок — нулевой overhead.

    Singleton — использовать через :func:`get_connection_reuse_manager`.
    """

    def __init__(self) -> None:
        """Инициализирует менеджер с пустым реестром pool'ов."""
        self._pools: dict[str, PoolRegistration] = {}

    # ------------------------------------------------------------------
    # Регистрация
    # ------------------------------------------------------------------

    def register_pool(
        self,
        name: str,
        pool: Any,
        ping_callable: Callable[[Any], Awaitable[Any]],
        max_lifetime_seconds: float = 3600.0,
        idle_timeout_seconds: float = 60.0,
    ) -> None:
        """Регистрирует pool с политиками lifetime + idle-ping.

        Повторная регистрация с тем же именем перезаписывает запись
        (идемпотентна). Можно выполнять до или после acquire.

        Args:
            name: Уникальное логическое имя pool.
            pool: Объект pool; хранится для справки и auto-recycle.
            ping_callable: Async-callable (pool: Any) → Any.
                Должен поднять исключение при недоступном backend.
            max_lifetime_seconds: Максимальное время жизни connection (сек).
                Connection старше этого порога пересоздаётся при acquire.
            idle_timeout_seconds: Порог простоя (сек) перед ping.
                Connection, простоявший дольше этого порога, проверяется
                ping_callable перед возвратом.
        """
        self._pools[name] = PoolRegistration(
            name=name,
            pool=pool,
            ping_callable=ping_callable,
            max_lifetime_seconds=max_lifetime_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
        logger.debug(
            "ConnectionReuseManager: pool зарегистрирован '%s' "
            "(max_lifetime=%.0fs, idle_timeout=%.0fs)",
            name,
            max_lifetime_seconds,
            idle_timeout_seconds,
        )

    # ------------------------------------------------------------------
    # Acquire / Release
    # ------------------------------------------------------------------

    async def acquire(self, name: str) -> Any:
        """Возвращает connection из зарегистрированного pool.

        Поведение зависит от feature-flag ``connection_reuse_manager``:

        - **Flag OFF**: немедленно возвращает ``pool`` без каких-либо проверок.
        - **Flag ON**: проверяет lifetime и idle-период connection:

          1. Если ``ConnectionMetadata.created_at`` старше ``max_lifetime_seconds``
             — выполняет auto-recycle (пересоздаёт метаданные, вызывает ping).
          2. Если ``ConnectionMetadata.last_used`` старше ``idle_timeout_seconds``
             — вызывает ``ping_callable`` для проверки backend.
          3. Обновляет ``last_used`` и инкрементирует ``use_count``.

        Args:
            name: Логическое имя зарегистрированного pool.

        Returns:
            Объект pool (или connection), готовый к использованию.

        Raises:
            KeyError: Если pool с таким именем не зарегистрирован.
            Exception: Если ping_callable выбросил исключение (backend недоступен).
        """
        registration = self._pools[name]

        if not _is_flag_enabled():
            # Флаг выключен — нулевой overhead
            return registration.pool

        now = time.monotonic()

        # Инициализация метаданных при первом acquire
        if registration.metadata is None:
            registration.metadata = ConnectionMetadata(
                name=name, created_at=now, last_used=now
            )
            registration.last_connection = registration.pool
            logger.debug("ConnectionReuseManager: первый acquire '%s'", name)

        meta = registration.metadata

        # Проверка lifetime: connection слишком старый → auto-recycle
        lifetime = now - meta.created_at
        if lifetime >= registration.max_lifetime_seconds:
            logger.info(
                "ConnectionReuseManager: '%s' превысил max_lifetime "
                "(%.0f / %.0fs) — auto-recycle",
                name,
                lifetime,
                registration.max_lifetime_seconds,
            )
            registration.metadata = ConnectionMetadata(
                name=name, created_at=now, last_used=now
            )
            meta = registration.metadata
            registration.last_connection = registration.pool
            # После recycle выполняем ping для проверки нового connection
            await self._ping(registration, now)
        elif (now - meta.last_used) >= registration.idle_timeout_seconds:
            # Connection простаивал дольше idle_timeout — проверяем ping
            logger.debug(
                "ConnectionReuseManager: '%s' idle %.0fs >= %.0fs — ping",
                name,
                now - meta.last_used,
                registration.idle_timeout_seconds,
            )
            await self._ping(registration, now)

        meta.last_used = now
        meta.use_count += 1
        return registration.last_connection

    async def release(self, name: str, conn: Any) -> None:
        """Освобождает connection обратно в pool.

        В текущей реализации выполняет обновление ``last_used`` и
        логирование. Физическое освобождение connection — ответственность
        вызывающего кода (зависит от типа pool).

        Args:
            name: Логическое имя pool.
            conn: Connection, возвращаемый в pool.
        """
        registration = self._pools.get(name)
        if registration is None:
            logger.warning("ConnectionReuseManager.release: pool '%s' не найден", name)
            return

        self.mark_used(name)
        logger.debug(
            "ConnectionReuseManager: release '%s' (use_count=%d)",
            name,
            registration.metadata.use_count if registration.metadata else 0,
        )

    def mark_used(self, name: str) -> None:
        """Обновляет метку last_used для connection в указанном pool.

        Вызывается после фактического использования connection.
        При выключенном feature-flag — no-op.

        Args:
            name: Логическое имя pool.
        """
        if not _is_flag_enabled():
            return

        registration = self._pools.get(name)
        if registration is not None and registration.metadata is not None:
            registration.metadata.last_used = time.monotonic()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ping(self, registration: PoolRegistration, now: float) -> None:
        """Выполняет ping_callable для проверки «живости» backend.

        При успехе обновляет ``last_used`` в метаданных.
        При ошибке логирует предупреждение и пробрасывает исключение.

        Args:
            registration: Запись зарегистрированного pool.
            now: Текущее monotonic-время (для обновления last_used).

        Raises:
            Exception: Если ping_callable завершился с ошибкой.
        """
        try:
            await registration.ping_callable(registration.pool)
            if registration.metadata is not None:
                registration.metadata.last_used = now
            logger.debug("ConnectionReuseManager: ping OK для '%s'", registration.name)
        except Exception as exc:
            logger.warning(
                "ConnectionReuseManager: ping FAIL для '%s' — %s",
                registration.name,
                exc,
            )
            raise


# ---------------------------------------------------------------------------
# Feature-flag lazy accessor
# ---------------------------------------------------------------------------


def _is_flag_enabled() -> bool:
    """Проверяет feature-flag ``connection_reuse_manager`` через lazy-import.

    Возвращает False при любой ошибке импорта (тесты без DI, CI).

    Returns:
        bool: True если флаг включён, иначе False.
    """
    try:
        from src.backend.core.config.features import feature_flags

        return feature_flags.connection_reuse_manager
    except Exception as _:
        return False


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_manager_instance: ConnectionReuseManager | None = None


def get_connection_reuse_manager() -> ConnectionReuseManager:
    """Возвращает singleton ConnectionReuseManager.

    Создаёт экземпляр при первом вызове (lazy-init). Singleton не создаёт
    background-задач — все проверки выполняются в момент вызова ``acquire``.

    Returns:
        ConnectionReuseManager: Единственный экземпляр в рамках процесса.
    """
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ConnectionReuseManager()
    return _manager_instance
