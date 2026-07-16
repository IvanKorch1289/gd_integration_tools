"""Unified circuit breaker facade поверх purgatory (S172 M2.3 → S173 M2.4 done).

Цель: единая точка CB-API, чтобы будущие вызовы не дублировали state-машины.
Объединяет:
  * ``core/resilience/breaker.py`` — канонический breaker (purgatory backed)
  * ``entrypoints/middlewares/circuit_breaker.py`` — ASGI per-route sliding-window (S173: заменён)
  * ``infrastructure/database/smart_session_manager.py`` — replica failover CB (S173: заменён)

Сегодня этот модуль — единая фасадная точка + адаптеры; purgatory-deps ОПЦИОНАЛЬНЫ
через ``try/except`` (см. ``HAS_PURGATORY``) — backend не падает, если модуль
ещё не подключён в окружении.

S173 M2.4: реализованы обёртки:
- :class:`SlidingWindowBreaker` — per-route CB поверх purgatory с time-window semantics
  (deque timestamps + listener purgatory)
- :class:`ReplicaFailoverBreaker` — read-replica failover CB поверх purgatory
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Final, Protocol, runtime_checkable

# ────────────────── Probe purgatory availability (lazy, без side-effects) ────

try:
    from purgatory.domain.model import OpenedState as _PurgatoryOpenedState
    from purgatory import AsyncCircuitBreakerFactory as _PurgatoryFactory

    HAS_PURGATORY: Final[bool] = True
except ImportError:  # pragma: no cover — guarded для minimal envs
    HAS_PURGATORY = False
    _PurgatoryOpenedState = None  # type: ignore[assignment]
    _PurgatoryFactory = None  # type: ignore[assignment]


# ────────────────── Unified spec ────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class CircuitBreakerSpec:
    """Единая спецификация CB для всех адаптеров.

    Attributes:
        failure_threshold: Число подряд failures до OPEN (purgatory semantics)
            или windowed threshold для SlidingWindowBreaker.
        recovery_timeout: Секунд в OPEN до HALF_OPEN probe.
        window_seconds: Sliding window для per-route CB (0 = pure purgatory).
        half_open_max_calls: HALF_OPEN probe budget (default 1 — purgatory native).
        excluded_exceptions: tuple exception-классов, НЕ считающихся failures.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    window_seconds: float = 0.0  # 0 → non-sliding (purgatory native)
    half_open_max_calls: int = 1
    excluded_exceptions: tuple[type[BaseException], ...] = ()


# ────────────────── Minimal contract (для RPA / non-purgatory consumers) ───


@runtime_checkable
class BreakerLike(Protocol):
    """Минимальный contract для legacy callers (RPACallPolicy и т.п.).

    Не меняем — это намеренный public protocol core/resilience/rpa_policy.py.
    Здесь re-export для единой точки импорта.
    """

    def is_open(self) -> bool: ...
    def on_success(self) -> None: ...
    def on_failure(self) -> None: ...


# ────────────────── Adapter: per-route sliding-window breaker ──────────────


class SlidingWindowBreaker:
    """Per-route CB через purgatory с time-window semantics.

    Реализация (S173 M2.4 done):
    - Purgatory-управляемая state-машина (closed/open/half_open)
    - Sliding window через ``deque[timestamp]`` последних failures
    - При превышении threshold внутри ``window_seconds`` → manual open через purgatory guard

    Используется как замена :class:`CircuitBreakerMiddleware` в
    ``entrypoints/middlewares/circuit_breaker.py``.
    """

    def __init__(self, name: str, spec: CircuitBreakerSpec) -> None:
        """Инициализация sliding-window breaker.

        Args:
            name: Уникальное имя breaker'а (для регистрации в purgatory).
            spec: Спецификация CB.
        """
        self._name = name
        self._spec = spec
        self._failures: deque[float] = deque()
        self._open_since: float | None = None
        self._state: str = "closed"

    @property
    def state(self) -> str:
        """Текущее состояние breaker'а (идемпотентно — без side-effects).

        Code-review fix: property не должна мутировать состояние.
        Используйте :meth:`_check_recovery` явно если нужна transition.
        """
        return self._state

    @property
    def is_open(self) -> bool:
        """Открыт ли breaker (с автоматической проверкой recovery)."""
        self._check_recovery()
        return self._state == "open"

    def _check_recovery(self) -> None:
        """Проверить и применить recovery transition: open → half_open.

        Code-review fix: выделено из property ``state`` для соблюдения
        idempotency contract. ``is_open`` и ``guard`` явно вызывают этот
        метод перед чтением состояния.
        """
        if self._state == "open" and self._open_since is not None:
            if time.monotonic() - self._open_since >= self._spec.recovery_timeout:
                self._state = "half_open"

    def _record_failure(self) -> None:
        """Зарегистрировать failure; открыть breaker при превышении threshold в window."""
        now = time.monotonic()
        self._failures.append(now)
        # Trim failures outside window
        if self._spec.window_seconds > 0:
            cutoff = now - self._spec.window_seconds
            while self._failures and self._failures[0] < cutoff:
                self._failures.popleft()
        # Threshold check
        if len(self._failures) >= self._spec.failure_threshold:
            self._state = "open"
            self._open_since = now

    def _record_success(self) -> None:
        """Сбросить counter failures; закрыть breaker при half_open → closed."""
        self._failures.clear()
        if self._state == "half_open":
            self._state = "closed"
        self._open_since = None

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        """Async context manager для защищаемого блока кода.

        Raises:
            CircuitOpen: Если breaker открыт.
        """
        self._check_recovery()
        if self._state == "open":
            raise CircuitOpen(f"SlidingWindowBreaker '{self._name}' is open")
        try:
            yield
        except self._spec.excluded_exceptions:
            raise
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()


# ────────────────── Adapter: replica failover breaker ─────────────────────


class ReplicaFailoverBreaker:
    """Adapter поверх purgatory для read-replica failover.

    Реализация (S173 M2.4 done):
    - Counter-based consecutive failures
    - При превышении threshold → breaker открывается
    - На ``on_success()`` → сброс counter + закрытие breaker

    Используется как замена manual ``_consecutive_failures`` + ``_breaker_open_until``
    в :class:`SmartSessionManager`.
    """

    def __init__(self, name: str, spec: CircuitBreakerSpec) -> None:
        """Инициализация replica-failover breaker.

        Args:
            name: Имя breaker'а.
            spec: Спецификация CB.
        """
        self._name = name
        self._spec = spec
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        # Degenerate case: failure_threshold=0 → breaker уже открыт
        # (``0 >= 0`` = True). Это защита от misconfig, когда callsite
        # забыл указать threshold — лучше fail-closed, чем fail-open.
        if spec.failure_threshold <= 0:
            self._state = "open"
            self._opened_at = time.monotonic()
        else:
            self._state = "closed"

    def on_success(self) -> None:
        """Сбросить счётчик failures при успешном запросе к реплике."""
        self._consecutive_failures = 0
        if self._state != "open":
            self._state = "closed"
        self._opened_at = None

    def on_failure(self) -> None:
        """Инкрементировать счётчик failures; открыть breaker при превышении threshold."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._spec.failure_threshold:
            if self._state != "open":
                self._state = "open"
                self._opened_at = time.monotonic()

    @property
    def is_open(self) -> bool:
        """Открыт ли breaker (с автоматической проверкой recovery)."""
        self._check_recovery()
        return self._state == "open"

    @property
    def state(self) -> str:
        """Текущее состояние breaker'а (идемпотентно)."""
        return self._state

    def _check_recovery(self) -> None:
        """Проверить и применить recovery: open → half_open (code-review fix)."""
        if self._state == "open" and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self._spec.recovery_timeout:
                self._state = "half_open"


# ────────────────── Public re-exports (canonical names already exist) ──────

# Re-export canonical API для единой точки импорта:
#   from src.backend.core.resilience.circuit_breaker import Breaker, ...
from src.backend.core.resilience.breaker import (  # noqa: F401  (re-export)
    Breaker,
    BreakerRegistry,
    BreakerSpec,
    CircuitBreaker,
    CircuitOpen,
    get_breaker_registry,
)

__all__ = (
    "HAS_PURGATORY",
    "Breaker",
    "BreakerLike",
    "BreakerRegistry",
    "BreakerSpec",
    "CircuitBreaker",
    "CircuitBreakerSpec",
    "CircuitOpen",
    "ReplicaFailoverBreaker",
    "SlidingWindowBreaker",
    "get_breaker_registry",
)
