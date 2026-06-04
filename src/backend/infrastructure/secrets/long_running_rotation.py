"""Long-running secret rotator для Temporal-activity (Sprint 4 Wave E).

Назначение:
    Облегчает работу с Vault-секретами внутри **долгоживущих**
    Temporal-activity (durable, может выполняться часами/днями). Без
    rotation такие activity не подхватывают обновления секрета после
    Vault-rotation: новый password/token остаётся в Vault, а activity
    держит устаревший в локальной переменной.

Архитектурные принципы:
    * Не привязан к конкретному VaultBackend — принимает любой объект
      с методом ``get(name)`` (см. :class:`SecretBackend` Protocol).
    * Optional heartbeat-callback позволяет вызывать
      ``temporalio.activity.heartbeat`` после re-fetch — Temporal
      продлевает activity-deadline и фиксирует прогресс.
    * Кеш — простой: один ключ-секрет на rotator. Если нужен пул
      секретов — caller создаёт несколько rotator'ов.
    * Использует ``time.monotonic`` (не ``time.time``) — иммунен
      к скачкам wall-clock'а.

Использование внутри Temporal activity::

    @activity.defn
    async def long_db_export(...):
        rotator = LongRunningSecretRotator(
            backend=vault_backend,
            secret_path="secret/data/db/postgres",
            refresh_interval_s=300.0,
            heartbeat=activity.heartbeat,
        )
        while not done:
            creds = await rotator.fetch_with_rotation()
            await do_chunk(creds)
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

__all__ = ("HeartbeatCallback", "LongRunningSecretRotator", "SecretBackendLike")

_logger = logging.getLogger("infrastructure.secrets.long_running_rotation")

HeartbeatCallback = Callable[..., Any]
"""Callable-сигнатура heartbeat'а Temporal.activity (sync или async)."""


class SecretBackendLike(Protocol):
    """Минимальный протокол backend'а секретов.

    Совместим с :class:`VaultBackend` / :class:`EnvBackend`. Реальный
    backend может предоставлять более широкий API; rotator использует
    только ``get(name)``.
    """

    def get(self, name: str) -> Any:  # pragma: no cover — Protocol stub
        """Прочитать секрет по пути; возвращает any-объект (SecretValue)."""
        ...


class LongRunningSecretRotator:
    """Кеширующий fetch + периодический refresh секрета.

    Args:
        backend: Backend секретов (см. :class:`SecretBackendLike`).
        secret_path: Путь секрета в backend'е.
        refresh_interval_s: Интервал между принудительными re-fetch'ами.
        heartbeat: Опц. callable для Temporal heartbeat — вызывается
            после успешного refresh.
        time_source: Опц. функция-источник времени (default —
            :func:`time.monotonic`). Подменяется в unit-тестах.

    Поведение ``fetch_with_rotation``:
        1. При первом вызове читает backend и кеширует значение
           вместе с меткой времени.
        2. На повторных вызовах: если прошло больше
           ``refresh_interval_s`` — повторно читает backend, обновляет
           кеш, вызывает ``heartbeat`` (если задан).
        3. Иначе возвращает закешированное значение.

    Поведение ``invalidate``:
        Сбрасывает кеш — следующий ``fetch_with_rotation`` пойдёт
        в backend без проверки интервала.
    """

    __slots__ = (
        "_backend",
        "_cached_value",
        "_heartbeat",
        "_last_fetched",
        "_lock",
        "_refresh_interval",
        "_secret_path",
        "_time_source",
    )

    def __init__(
        self,
        backend: SecretBackendLike,
        secret_path: str,
        *,
        refresh_interval_s: float = 300.0,
        heartbeat: HeartbeatCallback | None = None,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        if refresh_interval_s <= 0.0:
            raise ValueError("refresh_interval_s должен быть > 0")
        self._backend = backend
        self._secret_path = secret_path
        self._refresh_interval = refresh_interval_s
        self._heartbeat = heartbeat
        self._time_source = time_source or time.monotonic
        self._cached_value: Any | None = None
        self._last_fetched: float | None = None
        self._lock = asyncio.Lock()

    @property
    def secret_path(self) -> str:
        """Путь секрета (для диагностики)."""
        return self._secret_path

    async def fetch_with_rotation(self) -> Any:
        """Вернуть значение секрета, обновив его при истечении интервала.

        Returns:
            Объект, возвращаемый ``backend.get(secret_path)`` — обычно
            :class:`SecretValue` или ``dict[str, str]``.
        """
        async with self._lock:
            now = self._time_source()
            stale = (
                self._cached_value is None
                or self._last_fetched is None
                or (now - self._last_fetched) > self._refresh_interval
            )
            if not stale:
                return self._cached_value

            self._cached_value = self._backend.get(self._secret_path)
            self._last_fetched = now
            await self._invoke_heartbeat()
            return self._cached_value

    async def invalidate(self) -> None:
        """Сбросить кеш — следующий fetch принудительно пойдёт в backend."""
        async with self._lock:
            self._cached_value = None
            self._last_fetched = None

    async def _invoke_heartbeat(self) -> None:
        """Вызвать heartbeat-callback (sync или async, безопасно)."""
        if self._heartbeat is None:
            return
        try:
            result: Any = self._heartbeat()
            if inspect.isawaitable(result):
                awaitable: Awaitable[Any] = result
                await awaitable
        except Exception as _:
            _logger.exception("Heartbeat callback raised; suppressing")
