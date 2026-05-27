"""Pybreaker-adapter с Redis state persistence (default-OFF).

Waves:
* ``[wave:s16/k2-w4-pybreaker-replace]`` — DoD-9 Sprint 16 scaffold
  (Protocol + Fake + feature-gate);
* ``[wave:s18/w0-goal-driven-sweep-3-pybreaker-sdk]`` — полная SDK-реализация
  поверх ``pybreaker>=1.2.0`` с lazy-import и mapping состояний.

Назначение: контракт для замены ``purgatory``-based [Breaker] на
``pybreaker`` с опциональной персистентностью состояния в Redis
(restore-on-restart).

Архитектурное обоснование:
1. ``purgatory`` не персистирует state (после рестарта — closed).
2. ``pybreaker`` поддерживает state-storage (Redis/Memory) — DoD-9.
3. Адаптер с одинаковым API даёт нулевые breaking-changes для
   callsite'ов при включении ``feature_flag``.

Default-режим S18: фабрика по-прежнему возвращает [InMemoryPybreakerAdapter],
если ``v11.pybreaker_enabled=False`` или ``pybreaker`` не установлен. При
``v11.pybreaker_enabled=True`` И успешном импорте — возвращается
[PybreakerSDKAdapter] поверх настоящего ``pybreaker.CircuitBreaker``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

__all__ = (
    "BreakerState",
    "BreakerStateStorage",
    "FakeBreakerStateStorage",
    "InMemoryPybreakerAdapter",
    "PybreakerAdapter",
    "PybreakerSDKAdapter",
    "PybreakerSDKUnavailable",
    "make_pybreaker_adapter",
)

_logger = logging.getLogger("core.utils.pybreaker_adapter")

# Mapping pybreaker → наш Protocol: 'half-open' → 'half_open'.
_PYBREAKER_STATE_MAP: Final[dict[str, str]] = {
    "closed": "closed",
    "open": "open",
    "half-open": "half_open",
}


class PybreakerSDKUnavailable(RuntimeError):
    """Бросается, когда требуется SDK adapter, но ``pybreaker`` не импортируется."""


@dataclass(frozen=True, slots=True)
class BreakerState:
    """Состояние breaker'а для persistence.

    Attributes:
        name: Уникальное имя breaker'а.
        state: ``closed`` / ``open`` / ``half_open``.
        fail_counter: Текущий счётчик отказов.
        last_failure_at_iso: ISO-timestamp последнего отказа (или ``""``).
    """

    name: str
    state: str
    fail_counter: int
    last_failure_at_iso: str


@runtime_checkable
class BreakerStateStorage(Protocol):
    """Контракт persistence-слоя для pybreaker state.

    Реализуется ``RedisBreakerStateStorage`` (S17) и
    [FakeBreakerStateStorage] (in-memory, для тестов).
    """

    async def save(self, state: BreakerState) -> None:
        """Сохранить состояние breaker'а.

        Args:
            state: Snapshot для персистенции.
        """

    async def load(self, name: str) -> BreakerState | None:
        """Прочитать сохранённое состояние по имени.

        Args:
            name: Имя breaker'а.

        Returns:
            BreakerState или None, если не сохранено ранее.
        """


@runtime_checkable
class PybreakerAdapter(Protocol):
    """Контракт pybreaker-обёртки с state-persistence.

    Сигнатуры совместимы с текущим [Breaker]: ``call`` / ``state`` /
    ``failure_count``. Это позволяет встраивать adapter как drop-in
    при включённом feature-flag без изменений в callsite.
    """

    @property
    def state(self) -> str:
        """Текущее состояние: ``closed`` / ``open`` / ``half_open``."""

    @property
    def failure_count(self) -> int:
        """Счётчик отказов."""

    async def call(
        self, fn: Callable[..., Awaitable[object]], *args: object, **kwargs: object
    ) -> object:
        """Выполнить async-fn под защитой breaker'а.

        При open-state бросает исключение совместимое с CircuitOpen.

        Args:
            fn: Async-функция.
            *args: Позиционные аргументы.
            **kwargs: Именованные аргументы.

        Returns:
            Результат ``fn``.
        """


class FakeBreakerStateStorage:
    """In-memory реализация [BreakerStateStorage] для unit-тестов и dev_light."""

    def __init__(self) -> None:
        """Пустой dict в качестве backing-store."""
        self._store: dict[str, BreakerState] = {}

    async def save(self, state: BreakerState) -> None:
        """Сохранить snapshot."""
        self._store[state.name] = state

    async def load(self, name: str) -> BreakerState | None:
        """Прочитать snapshot."""
        return self._store.get(name)


class InMemoryPybreakerAdapter:
    """Простой реф-impl [PybreakerAdapter] без pybreaker-зависимости.

    Используется как default при ``pybreaker_enabled=False``. Логика
    идентична минимальному circuit-breaker: ``fail_max`` отказов
    подряд → open, restored через ``reset_timeout``.

    Для production будет заменён на ``pybreaker.CircuitBreaker(
    state_storage=RedisStorage)`` в carryover S17.
    """

    def __init__(
        self,
        *,
        name: str,
        fail_max: int = 5,
        reset_timeout: float = 60.0,
        storage: BreakerStateStorage | None = None,
    ) -> None:
        """Инициализация in-memory breaker.

        Args:
            name: Уникальное имя для persistence-ключа.
            fail_max: Порог отказов до open.
            reset_timeout: Через сколько секунд после open → half_open.
            storage: Опциональный persistence (для тестов restore).
        """
        self._name = name
        self._fail_max = fail_max
        self._reset_timeout = reset_timeout
        self._storage = storage or FakeBreakerStateStorage()
        self._state = "closed"
        self._fail_counter = 0
        self._last_failure_at_iso = ""

    @property
    def state(self) -> str:
        """Текущее состояние breaker'а."""
        return self._state

    @property
    def failure_count(self) -> int:
        """Счётчик неудачных вызовов."""
        return self._fail_counter

    async def call(
        self, fn: Callable[..., Awaitable[object]], *args: object, **kwargs: object
    ) -> object:
        """Выполнить ``fn`` под защитой breaker'а.

        Args:
            fn: Async-функция.
            *args: Позиционные аргументы для ``fn``.
            **kwargs: Именованные аргументы для ``fn``.

        Returns:
            Результат ``fn``.

        Raises:
            RuntimeError: при ``state == 'open'`` (имитация CircuitOpen).
            Exception: пробрасывает оригинальные исключения от ``fn``.
        """
        if self._state == "open":
            raise RuntimeError(f"circuit_open: {self._name}")
        try:
            result = await fn(*args, **kwargs)
        except Exception as _:
            await self._on_failure()
            raise
        else:
            await self._on_success()
            return result

    async def _on_failure(self) -> None:
        """Обработать отказ: инкремент counter; при достижении fail_max → open."""
        from datetime import datetime, timezone

        self._fail_counter += 1
        self._last_failure_at_iso = datetime.now(timezone.utc).isoformat()
        if self._fail_counter >= self._fail_max:
            self._state = "open"
            _logger.warning(
                "pybreaker_adapter %s → open (failures=%d)",
                self._name,
                self._fail_counter,
            )
        await self._persist()

    async def _on_success(self) -> None:
        """Обработать успех: сбросить counter; перейти в closed из half_open."""
        self._fail_counter = 0
        if self._state == "half_open":
            self._state = "closed"
        await self._persist()

    async def _persist(self) -> None:
        """Записать текущее состояние через storage."""
        await self._storage.save(
            BreakerState(
                name=self._name,
                state=self._state,
                fail_counter=self._fail_counter,
                last_failure_at_iso=self._last_failure_at_iso,
            )
        )

    async def restore(self) -> None:
        """Восстановить состояние из storage (вызов при startup).

        DoD-9: state-persistence — после рестарта breaker не должен
        начинать с ``closed`` если до рестарта он был ``open``.
        """
        saved = await self._storage.load(self._name)
        if saved is None:
            return
        self._state = saved.state
        self._fail_counter = saved.fail_counter
        self._last_failure_at_iso = saved.last_failure_at_iso
        _logger.info(
            "pybreaker_adapter %s restored state=%s failures=%d",
            self._name,
            self._state,
            self._fail_counter,
        )


class PybreakerSDKAdapter:
    """Реализация [PybreakerAdapter] поверх ``pybreaker`` SDK.

    Lazy-import ``pybreaker`` в ``__init__``: если SDK не установлен —
    бросается :class:`PybreakerSDKUnavailable`, чтобы фабрика могла
    откатиться на [InMemoryPybreakerAdapter].

    Привязка к нашему [PybreakerAdapter] контракту:

    * ``state`` — ``current_state`` pybreaker, с маппингом
      ``half-open → half_open``;
    * ``failure_count`` — ``fail_counter`` SDK;
    * ``call`` — обёртка над ``call_async`` SDK.

    Args:
        name: Имя breaker'а (попадает в логи pybreaker).
        fail_max: Порог отказов до open.
        reset_timeout: Через сколько секунд possible recovery.
        state_storage: Опциональный ``pybreaker.CircuitBreakerStorage``
            (например, ``CircuitRedisStorage``). При None pybreaker
            держит state в памяти процесса (нет persistence).

    Raises:
        PybreakerSDKUnavailable: Если ``pybreaker`` не импортируется.
    """

    def __init__(
        self,
        *,
        name: str,
        fail_max: int = 5,
        reset_timeout: float = 60.0,
        state_storage: Any | None = None,
    ) -> None:
        try:
            import pybreaker  # type: ignore[import-not-found]
        except ImportError as exc:
            raise PybreakerSDKUnavailable(
                "pybreaker не установлен; добавьте extras [circuit-breaker]."
            ) from exc

        self._name = name
        cb_kwargs: dict[str, Any] = {
            "fail_max": fail_max,
            "reset_timeout": reset_timeout,
            "name": name,
        }
        if state_storage is not None:
            cb_kwargs["state_storage"] = state_storage
        self._cb = pybreaker.CircuitBreaker(**cb_kwargs)
        self._pybreaker_error: type[BaseException] = pybreaker.CircuitBreakerError

    @property
    def state(self) -> str:
        """Текущее состояние с mapping ``half-open`` → ``half_open``."""
        raw = str(self._cb.current_state)
        return _PYBREAKER_STATE_MAP.get(raw, raw)

    @property
    def failure_count(self) -> int:
        """Счётчик последовательных отказов pybreaker."""
        return int(self._cb.fail_counter)

    async def call(
        self, fn: Callable[..., Awaitable[object]], *args: object, **kwargs: object
    ) -> object:
        """Выполнить ``fn`` через ``pybreaker.call_async``.

        Args:
            fn: Async-функция.
            *args: Позиционные аргументы.
            **kwargs: Именованные аргументы.

        Returns:
            Результат ``fn``.

        Raises:
            pybreaker.CircuitBreakerError: При open-state.
            Exception: Прокидываются оригинальные исключения от ``fn``.
        """
        return await self._cb.call_async(fn, *args, **kwargs)

    async def restore(self) -> None:
        """No-op: pybreaker персистирует через ``state_storage`` автоматически.

        Метод оставлен для совместимости с [InMemoryPybreakerAdapter.restore].
        """
        return None


def _is_pybreaker_available() -> bool:
    """Lazy-check доступности pybreaker SDK без побочных эффектов."""
    try:
        import pybreaker  # noqa: F401  # type: ignore[import-not-found]
    except ImportError:
        return False
    return True


def make_pybreaker_adapter(
    *,
    name: str,
    fail_max: int = 5,
    reset_timeout: float = 60.0,
    storage: BreakerStateStorage | None = None,
    sdk_state_storage: Any | None = None,
) -> PybreakerAdapter:
    """Фабрика [PybreakerAdapter] для использования из application-кода.

    Логика выбора реализации:

    1. Если ``v11.pybreaker_enabled=True`` И ``pybreaker`` импортируется —
       возвращает :class:`PybreakerSDKAdapter` (production-путь).
    2. Иначе — :class:`InMemoryPybreakerAdapter` (default/тесты).

    Параметр ``storage`` относится **только** к InMemory-реализации (наш
    :class:`BreakerStateStorage`). Для SDK-пути персистенцию задаёт
    ``sdk_state_storage`` (например, ``pybreaker.CircuitRedisStorage``).

    Args:
        name: Уникальное имя breaker'а (ключ persistence).
        fail_max: Порог отказов до state=open.
        reset_timeout: Через сколько секунд возможно восстановление.
        storage: Опциональный наш backend для InMemory-реализации.
        sdk_state_storage: Опциональный native pybreaker state_storage
            (используется только при возврате [PybreakerSDKAdapter]).

    Returns:
        Объект, удовлетворяющий [PybreakerAdapter]-протоколу.
    """
    try:
        from src.backend.core.config.v11 import v11_settings

        sdk_enabled = bool(v11_settings.pybreaker_enabled)
    except Exception:  # noqa: BLE001  # на ранней инициализации возможны импорт-ошибки
        sdk_enabled = False

    if sdk_enabled and _is_pybreaker_available():
        try:
            return PybreakerSDKAdapter(
                name=name,
                fail_max=fail_max,
                reset_timeout=reset_timeout,
                state_storage=sdk_state_storage,
            )
        except PybreakerSDKUnavailable as exc:
            _logger.warning(
                "pybreaker_enabled=True, но SDK недоступен (%s); fallback на InMemory.",
                exc,
            )

    return InMemoryPybreakerAdapter(
        name=name,
        fail_max=fail_max,
        reset_timeout=reset_timeout,
        storage=storage,
    )
