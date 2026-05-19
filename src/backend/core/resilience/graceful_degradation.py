"""GracefulDegradationRegistry — per-feature toggling в degraded handler (S13 K2 W4).

Назначение:
    Дополняет :class:`ResilienceCoordinator` (per-call gating) на
    feature-level: каждый продуктовый feature заранее регистрирует
    «полный» и «деградированный» handler, плюс error-rate threshold;
    реестр сам переключает feature в degraded-mode при превышении
    порога и возвращает обратно при стабилизации.

Use-case::

    registry.register(
        DegradationFeature(
            name="search.with_personalization",
            full_handler=full_personalized_search,
            degraded_handler=plain_text_search,
            error_threshold=0.3,    # 30% ошибок → degraded
            recovery_threshold=0.05  # 5% ошибок → healthy
        )
    )
    # рантайм после каждого вызова:
    registry.record_outcome("search.with_personalization", success=True)
    # выбор handler перед вызовом:
    handler = registry.get_handler("search.with_personalization")

Алгоритм:
    Sliding window 100 outcome'ов (collections.deque(maxlen=100)) на
    каждый feature. После каждого ``record_outcome`` рассчитывается
    error rate; в зависимости от текущего state и порогов выполняется
    переход:

    * ``healthy`` → ``degraded`` при ``error_rate >= error_threshold``
    * ``degraded`` → ``recovering`` при ``error_rate <= recovery_threshold``
    * ``recovering`` → ``healthy`` при выдержанной стабильной выборке
      (мин. полное окно собрано после входа в recovering).

Потокобезопасность:
    Реестр защищён :class:`asyncio.Lock` — конкурентные
    ``record_outcome`` из разных корутин одного loop'а сериализуются.
    Для multi-process — используйте per-process реестр.

Ортогональность с :class:`DegradationManager`:
    DegradationManager отслеживает доступность инфраструктурных
    компонент (db/redis) по failure_count; GracefulDegradationRegistry
    отслеживает feature-level error rate по sliding window. Их можно
    использовать одновременно — registry поверх coordinator.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

__all__ = (
    "DegradationFeature",
    "FeatureState",
    "GracefulDegradationRegistry",
)

_logger = logging.getLogger("core.resilience.graceful_degradation")

# Размер sliding-window для расчёта error rate (см. record_outcome).
_DEFAULT_WINDOW_SIZE: Final[int] = 100


class FeatureState(Enum):
    """Текущее состояние feature.

    * :attr:`HEALTHY` — feature работает на full_handler.
    * :attr:`DEGRADED` — переключён на degraded_handler из-за высокого
      error rate.
    * :attr:`RECOVERING` — error rate упал ниже recovery_threshold, идёт
      повторное окно стабильности перед возвращением в HEALTHY.
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RECOVERING = "recovering"


@dataclass(frozen=True, slots=True)
class DegradationFeature:
    """Декларация feature для регистрации в реестре.

    Args:
        name: уникальный идентификатор feature (например
            ``"search.with_personalization"``).
        full_handler: callable полнофункциональной реализации.
        degraded_handler: callable упрощённой fallback-реализации.
        error_threshold: error rate (0..1), при котором происходит
            переход HEALTHY → DEGRADED (default 0.3).
        recovery_threshold: error rate (0..1), при котором происходит
            переход DEGRADED → RECOVERING (default 0.05).
        window_size: размер sliding-window outcomes (default 100).
    """

    name: str
    full_handler: Callable[..., Any]
    degraded_handler: Callable[..., Any]
    error_threshold: float = 0.3
    recovery_threshold: float = 0.05
    window_size: int = _DEFAULT_WINDOW_SIZE


@dataclass(slots=True)
class _FeatureRuntime:
    """Внутренний runtime-state одного feature (sliding window + state)."""

    feature: DegradationFeature
    state: FeatureState = FeatureState.HEALTHY
    outcomes: deque[bool] = field(default_factory=lambda: deque(maxlen=100))


class GracefulDegradationRegistry:
    """Singleton-style реестр feature-level degradation.

    Создаётся один экземпляр на процесс. Конкурентные ``record_outcome``
    защищены одним :class:`asyncio.Lock`.
    """

    def __init__(self) -> None:
        """Создаёт пустой реестр."""
        self._features: dict[str, _FeatureRuntime] = {}
        self._lock = asyncio.Lock()

    # ─── Регистрация ──────────────────────────────────────────────────────

    def register(self, feature: DegradationFeature) -> None:
        """Регистрирует feature; повторная регистрация перезаписывает прежнюю.

        Args:
            feature: декларация :class:`DegradationFeature`.
        """
        self._features[feature.name] = _FeatureRuntime(
            feature=feature,
            outcomes=deque(maxlen=feature.window_size),
        )
        _logger.debug(
            "graceful_degradation.register",
            extra={"feature": feature.name, "window": feature.window_size},
        )

    def is_registered(self, name: str) -> bool:
        """Проверяет, зарегистрирован ли feature."""
        return name in self._features

    # ─── Получение handler ────────────────────────────────────────────────

    def get_handler(self, name: str) -> Callable[..., Any] | None:
        """Возвращает текущий handler feature по его state.

        Args:
            name: имя feature.

        Returns:
            full_handler если state ∈ ``{HEALTHY, RECOVERING}`` или
            degraded_handler если ``state == DEGRADED``. Если feature
            не зарегистрирован — ``None``.
        """
        runtime = self._features.get(name)
        if runtime is None:
            return None
        if runtime.state == FeatureState.DEGRADED:
            return runtime.feature.degraded_handler
        return runtime.feature.full_handler

    def get_state(self, name: str) -> FeatureState | None:
        """Возвращает текущий state feature или ``None`` если не зарегистрирован."""
        runtime = self._features.get(name)
        return runtime.state if runtime is not None else None

    # ─── Учёт результатов вызовов ─────────────────────────────────────────

    async def record_outcome(self, name: str, *, success: bool) -> FeatureState:
        """Регистрирует outcome вызова feature и пересчитывает state.

        Args:
            name: имя feature.
            success: ``True`` если вызов прошёл успешно, ``False`` иначе.

        Returns:
            Актуальный state после пересчёта. Если feature не
            зарегистрирован — :attr:`FeatureState.HEALTHY` (fallback).
        """
        async with self._lock:
            runtime = self._features.get(name)
            if runtime is None:
                # Неизвестный feature — full handler по умолчанию.
                return FeatureState.HEALTHY
            runtime.outcomes.append(bool(success))
            self._recompute_state(runtime)
            return runtime.state

    def _recompute_state(self, runtime: _FeatureRuntime) -> None:
        """Пересчитывает state по текущему окну outcomes."""
        outcomes = runtime.outcomes
        if not outcomes:
            return
        error_rate = sum(1 for o in outcomes if not o) / len(outcomes)
        feature = runtime.feature

        prev_state = runtime.state
        if runtime.state == FeatureState.HEALTHY:
            if error_rate >= feature.error_threshold:
                runtime.state = FeatureState.DEGRADED
        elif runtime.state == FeatureState.DEGRADED:
            if error_rate <= feature.recovery_threshold:
                runtime.state = FeatureState.RECOVERING
                # Если окно уже стабилизировалось (полное и rate низкий) —
                # пропускаем RECOVERING-cooldown и сразу возвращаемся в HEALTHY.
                if (
                    len(outcomes) >= feature.window_size
                    and error_rate <= feature.recovery_threshold
                ):
                    runtime.state = FeatureState.HEALTHY
        elif runtime.state == FeatureState.RECOVERING:
            # Возвращаемся в HEALTHY только когда окно полностью
            # пересобрано и error_rate всё ещё ниже recovery_threshold.
            if (
                len(outcomes) >= feature.window_size
                and error_rate <= feature.recovery_threshold
            ):
                runtime.state = FeatureState.HEALTHY
            elif error_rate >= feature.error_threshold:
                # Снова сбой — обратно в DEGRADED.
                runtime.state = FeatureState.DEGRADED

        if runtime.state != prev_state:
            _logger.info(
                "graceful_degradation.state_changed",
                extra={
                    "feature": feature.name,
                    "from": prev_state.value,
                    "to": runtime.state.value,
                    "error_rate": round(error_rate, 4),
                },
            )

    # ─── Ручное управление ────────────────────────────────────────────────

    def recover(self, name: str) -> None:
        """Ручной сброс feature в HEALTHY (очищает окно outcomes).

        Используется при known-good restore (например, после ручного
        фикса bug'а), когда не нужно ждать полного окна.

        Args:
            name: имя feature.
        """
        runtime = self._features.get(name)
        if runtime is None:
            return
        runtime.outcomes.clear()
        prev_state = runtime.state
        runtime.state = FeatureState.HEALTHY
        if prev_state != FeatureState.HEALTHY:
            _logger.info(
                "graceful_degradation.manual_recover",
                extra={"feature": name, "from": prev_state.value},
            )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Возвращает dict-снимок всех зарегистрированных features.

        Полезно для admin-endpoint /tech/degradation.
        """
        return {
            name: {
                "state": rt.state.value,
                "samples": len(rt.outcomes),
                "error_rate": (
                    round(sum(1 for o in rt.outcomes if not o) / len(rt.outcomes), 4)
                    if rt.outcomes
                    else 0.0
                ),
            }
            for name, rt in self._features.items()
        }


# Глобальный singleton — может быть инжектирован в DI.
_registry_singleton: GracefulDegradationRegistry | None = None


def get_graceful_degradation_registry() -> GracefulDegradationRegistry:
    """Возвращает (создавая при необходимости) глобальный singleton."""
    global _registry_singleton  # noqa: PLW0603
    if _registry_singleton is None:
        _registry_singleton = GracefulDegradationRegistry()
    return _registry_singleton
