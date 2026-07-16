"""Unified circuit breaker facade поверх purgatory (S172 M2.3 Option C).

Цель: единая точка CB-API, чтобы будущие вызовы не дублировали state-машины.
Объединяет:
  * ``core/resilience/breaker.py`` — канонический breaker (purgatory backed)
  * ``entrypoints/middlewares/circuit_breaker.py`` — ASGI per-route sliding-window
  * ``infrastructure/database/smart_session_manager.py`` — replica failover CB

Сегодня этот модуль — тонкий re-export + адаптеры; purgatory-deps ОПЦИОНАЛЬНЫ
через ``try/except`` (см. ``HAS_PURGATORY``) — backend не падает, если модуль
ещё не подключён в окружении.

ВНИМАНИЕ: это SCAFFOLD (S172 M2.3) — без активной интеграции в callsite.
Полная миграция запланирована в S172 M2.4 (замена middleware/smart_session
на адаптеры ниже). До того момента существующие реализации работают как есть.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Protocol

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

    TODO(s172/m2.4): заменить ``entrypoints/middlewares/circuit_breaker.py``
    на этот адаптер (state-machine → purgatory ``AsyncCircuitBreakerFactory``
    с ``add_listener`` для per-route state и TimeLimiter для sliding window).

    ВНИМАНИЕ: purgatory сам по себе НЕ поддерживает sliding window —
    требуется обёртка из deque timestamps + listener, который
    переоткрывает breaker по истечении ``window_seconds``. Полная
    реализация — в S172 M2.4.
    """

    def __init__(self, name: str, spec: CircuitBreakerSpec) -> None:
        """Инициализация sliding-window breaker.

        Args:
            name: Уникальное имя breaker'а (для регистрации в purgatory).
            spec: Спецификация CB.
        """
        self._name = name
        self._spec = spec

    @property
    def state(self) -> str:
        """Текущее состояние breaker'а."""
        # TODO(s172/m2.4): делегировать в purgatory через listener.
        return "closed"

    def guard(self) -> Any:
        """Async context manager для защищаемого блока кода."""
        # TODO(s172/m2.4): вернуть purgatory-guard.
        raise NotImplementedError("S172 M2.4: pending purgatory integration")


# ────────────────── Adapter: replica failover breaker ─────────────────────


class ReplicaFailoverBreaker:
    """Adapter поверх purgatory для read-replica failover.

    TODO(s172/m2.4): заменить ``infrastructure/database/smart_session_manager.py``
    на этот адаптер; ``_record_replica_failure`` → ``on_failure()``,
    ``replica_breaker_open`` → ``breaker.is_open``.
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

    def on_success(self) -> None:
        """Сбросить счётчик failures при успешном запросе к реплике."""
        self._consecutive_failures = 0

    def on_failure(self) -> None:
        """Инкрементировать счётчик failures."""
        self._consecutive_failures += 1

    @property
    def is_open(self) -> bool:
        """Открыт ли breaker (превышен ли threshold)."""
        return self._consecutive_failures >= self._spec.failure_threshold


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
