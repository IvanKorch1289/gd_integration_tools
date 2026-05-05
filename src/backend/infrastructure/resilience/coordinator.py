"""ResilienceCoordinator — координатор fallback-политик (Wave W26).

Тонкая надстройка над ``BreakerRegistry`` (purgatory) и
``DegradationManager`` (graceful degradation). Не заменяет их, а
объединяет: для каждого зарегистрированного компонента ведёт
упорядоченную цепочку backend'ов и при OPEN-breaker прозрачно
переключается на следующий backend.

Контракт коротко::

    coordinator = get_resilience_coordinator()
    coordinator.register(
        component="db_main",
        primary=primary_pg_callable,
        fallbacks={"sqlite_ro": sqlite_callable},
        chain=["sqlite_ro"],
        breaker_spec=BreakerSpec(threshold=5, recovery_timeout=30.0),
        mode="auto",
    )
    result = await coordinator.call("db_main", *args, **kwargs)

Семантика mode:
    * ``auto`` — primary вызывается, при OPEN-breaker идём по chain;
    * ``forced`` — primary не вызывается, сразу идём по chain (dev_light);
    * ``off`` — fallback выключен, отказ primary распространяется наружу.

Coordinator не имеет ABC в ``core/interfaces/`` — намеренно: единственная
реализация, fallback-цепочки описываются декларативно в YAML, ABC создаст
overhead без преимуществ (см. Правило 13 в PLAN.md).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from src.backend.core.config.services.resilience import (
    BreakerProfile,
    FallbackPolicy,
    ResilienceSettings,
)
from src.backend.core.resilience import DegradationManager, degradation_manager
from src.backend.infrastructure.resilience.breaker import (
    Breaker,
    BreakerRegistry,
    BreakerSpec,
    CircuitOpen,
    breaker_registry,
)

__all__ = (
    "ComponentStatus",
    "ResilienceCoordinator",
    "get_resilience_coordinator",
    "set_resilience_coordinator",
)

logger = logging.getLogger(__name__)

FallbackMode = Literal["auto", "forced", "off"]
DegradationLabel = Literal["normal", "degraded", "down"]

AsyncCallable = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class _Component:
    """Внутреннее состояние одного компонента в координаторе."""

    name: str
    primary: AsyncCallable | None
    fallbacks: dict[str, AsyncCallable]
    chain: list[str]
    breaker: Breaker
    mode: FallbackMode
    last_used_backend: str = "primary"


@dataclass(slots=True, frozen=True)
class ComponentStatus:
    """Снимок состояния компонента, возвращается ``status()``."""

    name: str
    breaker_state: str  # closed | open | half_open
    mode: FallbackMode
    chain: list[str] = field(default_factory=list)
    last_used_backend: str = "primary"
    degradation: DegradationLabel = "normal"


class ResilienceCoordinator:
    """Координатор fallback-политик поверх breaker-реестра.

    Связь с другими компонентами:
        * ``BreakerRegistry`` (purgatory) — собственно state-machine
          breaker'ов; coordinator их не дублирует, а переиспользует;
        * ``DegradationManager`` — agregате degradation_mode (FULL /
          DEGRADED / EMERGENCY) сигнализируется обратно по итогам каждого
          вызова;
        * YAML ``resilience:`` — источник профилей и chain'ов
          (см. ``ResilienceSettings``).
    """

    def __init__(
        self,
        breakers: BreakerRegistry | None = None,
        degradation: DegradationManager | None = None,
    ) -> None:
        self._breakers = breakers or breaker_registry
        self._degradation = degradation or degradation_manager
        self._components: dict[str, _Component] = {}

    # ─────────── Регистрация ───────────

    def register(
        self,
        component: str,
        *,
        primary: AsyncCallable | None,
        fallbacks: dict[str, AsyncCallable],
        chain: list[str],
        breaker_spec: BreakerSpec | None = None,
        mode: FallbackMode = "auto",
    ) -> None:
        """Регистрирует компонент с primary-callable и fallback-цепочкой.

        ``primary`` может быть ``None`` для компонентов, у которых нет
        primary backend'а в текущем профиле (например, dev_light) —
        тогда автоматически принудительно используется ``mode='forced'``.

        Все ``chain`` идентификаторы должны присутствовать в ``fallbacks``.
        """
        unknown = [name for name in chain if name not in fallbacks]
        if unknown:
            raise ValueError(
                f"Fallback chain для '{component}' содержит "
                f"незарегистрированные backend'ы: {unknown}"
            )

        breaker = self._breakers.get_or_create(component, breaker_spec)
        effective_mode: FallbackMode = mode if primary is not None else "forced"

        comp = _Component(
            name=component,
            primary=primary,
            fallbacks=fallbacks,
            chain=list(chain),
            breaker=breaker,
            mode=effective_mode,
        )
        self._components[component] = comp
        self._degradation.register(component)
        # Публикуем начальный gauge, чтобы метрика появлялась в /metrics
        # сразу при старте, а не только после первого call().
        self._publish_degradation(comp)
        logger.info(
            "Resilience component registered: %s (mode=%s, chain=%s)",
            component,
            effective_mode,
            chain,
        )

    def register_from_settings(
        self,
        component: str,
        *,
        primary: AsyncCallable | None,
        fallbacks: dict[str, AsyncCallable],
        settings: ResilienceSettings,
    ) -> None:
        """Удобный helper: берёт chain/mode/breaker_spec из YAML-настроек."""
        policy = settings.fallbacks.get(component, FallbackPolicy())
        profile = settings.breakers.get(component, BreakerProfile())
        mode: FallbackMode = (
            settings.fallback_mode_override
            if settings.fallback_mode_override is not None
            else policy.mode
        )
        spec = BreakerSpec(
            failure_threshold=profile.threshold, recovery_timeout=profile.ttl
        )
        self.register(
            component=component,
            primary=primary,
            fallbacks=fallbacks,
            chain=policy.chain,
            breaker_spec=spec,
            mode=mode,
        )

    # ─────────── Вызов ───────────

    async def call(self, component: str, *args: Any, **kwargs: Any) -> Any:
        """Вызывает primary, при отказе/OPEN — идёт по chain."""
        comp = self._components.get(component)
        if comp is None:
            raise KeyError(f"Resilience component не зарегистрирован: {component}")

        if comp.mode != "forced" and comp.primary is not None:
            try:
                async with comp.breaker.guard():
                    result = await comp.primary(*args, **kwargs)
                self._mark_success(comp, "primary")
                return result
            except CircuitOpen:
                logger.warning(
                    "Breaker OPEN for '%s' — переключаемся на fallback chain", comp.name
                )
                self._mark_failure(comp)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Primary call failed for '%s' (%s) — пробуем fallback chain",
                    comp.name,
                    type(exc).__name__,
                )
                self._mark_failure(comp)

        if comp.mode == "off":
            raise RuntimeError(
                f"Resilience: primary '{comp.name}' упал, fallback mode=off"
            )

        last_exc: Exception | None = None
        for backend_name in comp.chain:
            backend = comp.fallbacks[backend_name]
            try:
                result = await backend(*args, **kwargs)
                self._mark_success(comp, backend_name)
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Fallback backend '%s' (component '%s') упал: %s",
                    backend_name,
                    comp.name,
                    type(exc).__name__,
                )

        raise RuntimeError(
            f"Resilience: все backend'ы '{comp.name}' исчерпаны"
        ) from last_exc

    # ─────────── Snapshot для health-aggregator ───────────

    def status(self) -> dict[str, ComponentStatus]:
        """Возвращает снимок состояния всех зарегистрированных компонентов."""
        return {
            comp.name: ComponentStatus(
                name=comp.name,
                breaker_state=comp.breaker.state,
                mode=comp.mode,
                chain=list(comp.chain),
                last_used_backend=comp.last_used_backend,
                degradation=self._degradation_label(comp),
            )
            for comp in self._components.values()
        }

    def degradation_mode(self, component: str) -> DegradationLabel:
        """Возвращает текущий ярлык degradation для одного компонента."""
        comp = self._components.get(component)
        return "normal" if comp is None else self._degradation_label(comp)

    def list_components(self) -> list[str]:
        """Имена всех зарегистрированных компонентов (для health-checks)."""
        return list(self._components.keys())

    # ─────────── Внутреннее ───────────

    def _mark_success(self, comp: _Component, backend: str) -> None:
        comp.last_used_backend = backend
        if backend == "primary":
            self._degradation.report_success(comp.name)
        self._publish_degradation(comp)

    def _mark_failure(self, comp: _Component) -> None:
        self._degradation.report_failure(comp.name)
        self._publish_degradation(comp)

    @staticmethod
    def _degradation_label(comp: _Component) -> DegradationLabel:
        if comp.last_used_backend == "primary" and comp.breaker.state == "closed":
            return "normal"
        if comp.last_used_backend != "primary" and comp.chain:
            return "degraded"
        return "down"

    def _publish_degradation(self, comp: _Component) -> None:
        """Публикует gauge ``app_degradation_mode`` для компонента.

        Импорт лениво и в try/except, чтобы отсутствие prometheus-зависимости
        в минимальном окружении (тесты, dev_light без observability) не
        ломало работу coordinator'а.
        """
        try:
            from src.backend.infrastructure.observability.client_metrics import (
                record_degradation_mode,
            )

            record_degradation_mode(
                component=comp.name, label=self._degradation_label(comp)
            )
        except ImportError:
            pass


_coordinator: ResilienceCoordinator | None = None


def get_resilience_coordinator() -> ResilienceCoordinator:
    """Возвращает singleton-координатора. Создаёт при первом вызове."""
    global _coordinator
    if _coordinator is None:
        _coordinator = ResilienceCoordinator()
    return _coordinator


def set_resilience_coordinator(coordinator: ResilienceCoordinator | None) -> None:
    """Подменяет singleton (нужно для тестов и lifespan-shutdown)."""
    global _coordinator
    _coordinator = coordinator
