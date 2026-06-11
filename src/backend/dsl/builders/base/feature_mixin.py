from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

"""Base-модуль RouteBuilder.

Содержит сам класс ``RouteBuilder`` (``@dataclass(slots=True)``) и его
core-методы: точки входа, ``_add`` / ``_add_lazy`` helpers, pipeline
composition (process / to / process_fn / include), chainable per-step
modifiers (with_timeout/retries/headers/auth), core-процессоры
(set_header/set_property/log/validate/feature_flag),
generic-helpers (shadow_mode/bulkhead/lineage/ab_test/feature_flag_branch),
business-helpers (tenant_scope/cost_tracker/outbox/mask/compliance_labels),
а также ``build()`` + ``_validate_action_names()``.

Контракт миксинов (см. ADR DSL Foundation Refactor 2026-05):

* mixin'ы — **stateless** поведенческие классы: только методы.
* mixin'ы **не имеют** ``@dataclass`` декоратора.
* mixin'ы **объявляют** пустой ``__slots__ = ()`` — обязательно для
  совместимости с ``RouteBuilder(@dataclass(slots=True))``: пустой tuple
  снимает ``__dict__`` overhead, не конфликтует с lay-out наследника
  и проходит ``mypy`` strict.
* mixin'ы **не имеют** instance-атрибутов; всё состояние живёт в
  ``RouteBuilder`` (``route_id``, ``source``, ``description``,
  ``_processors``, ``_protocol``, ``_transport_config``,
  ``_feature_flag``).
* приватные утилиты (``_add``, ``_add_lazy``, ``_last_processor_or_raise``,
  ``_set_first_attr``, ``_validate_action_names``) живут на
  ``RouteBuilder`` и доступны через ``self``.
"""

from collections.abc import Callable

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import BaseProcessor


class FeatureMixin:
    """feature flags + AB testing для RouteBuilder. S57 W1 extraction."""

    __slots__ = ()

    def feature_flag(self, name: str) -> RouteBuilder:
        """Привязывает маршрут к feature flag (можно отключить без рестарта)."""
        self._feature_flag = name
        return self

    def shadow_mode(self, processors: list[BaseProcessor]) -> RouteBuilder:
        """Исполняет вложенную ветку в shadow-режиме (без side effects)."""
        from src.backend.dsl.engine.processors.generic import ShadowModeProcessor

        return self._add(ShadowModeProcessor(processors=processors))

    def ab_test(
        self,
        variant_a: list[BaseProcessor],
        variant_b: list[BaseProcessor],
        *,
        split_percent: int = 50,
        key_fn: Callable[[Exchange[Any]], str] | None = None,
    ) -> RouteBuilder:
        """Стабильная маршрутизация X% трафика на вариант B."""
        from src.backend.dsl.engine.processors.generic import AbTestRouterProcessor

        return self._add(
            AbTestRouterProcessor(
                variant_a=variant_a,
                variant_b=variant_b,
                split_percent=split_percent,
                key_fn=key_fn,
            )
        )

    def feature_flag_branch(
        self,
        flag: str,
        processors: list[BaseProcessor],
        *,
        resolver: Callable[[str], bool] | None = None,
    ) -> RouteBuilder:
        """Выполняет ветку процессоров только при включённом feature flag.

        Не путать с ``feature_flag(name)`` (метаданная маршрута, отключает
        маршрут целиком). Здесь — DSL-step внутри pipeline.
        """
        from src.backend.dsl.engine.processors.generic import FeatureFlagGuardProcessor

        return self._add(
            FeatureFlagGuardProcessor(
                flag=flag, processors=processors, resolver=resolver
            )
        )
