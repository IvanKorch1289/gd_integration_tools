from __future__ import annotations

from typing import Any, Self

from src.backend.dsl.builders.base._protocol import _RouteBuilderProtocol

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


class FeatureMixin(_RouteBuilderProtocol):
    """feature flags + AB testing для RouteBuilder. S57 W1 extraction."""

    __slots__ = ()

    def feature_flag(
        self,
        name: str | None = None,
        *,
        flag: str | None = None,
        default: bool = True,
        stop_on_disabled: bool = False,
        output_field: str = "_flag_enabled",
    ) -> Self:
        """Привязывает маршрут к feature flag (можно отключить без рестарта).

        Поддерживаются обе формы вызова, которые используются в проекте:

        * позиционная — ``.feature_flag("my_flag")``;
        * именованная — ``.feature_flag(flag="my_flag", default=True,
          stop_on_disabled=False, output_field="demo_active")``, как в
          YAML-шаге ``routes/*/*.dsl.yaml`` и в примере
          ``FeatureFlagCheckProcessor``.

        Раньше принимался только позиционный ``name``, из-за чего YAML-шаг
        падал с ``TypeError: feature_flag() got an unexpected keyword
        argument 'flag'`` — то есть любой route с этим шагом не загружался.

        **Семантика и известное расхождение.** Здесь флаг — это
        **route-level гейт**: ``Pipeline.feature_flag`` проверяется в
        ``execution_engine._check_feature_flag()``, и выключенный флаг
        останавливает весь pipeline целиком. Параметры ``default``,
        ``stop_on_disabled`` и ``output_field`` относятся к другой фиче —
        пошаговой проверке ``FeatureFlagCheckProcessor``, которая пишет
        результат в ``exchange.properties[output_field]`` и не обязана
        останавливать pipeline. Здесь они принимаются и сохраняются как
        декларация, чтобы YAML компилировался, но процессор не создаётся:
        иначе флаг проверялся бы дважды, и ``stop_on_disabled`` из YAML
        молчал бы расходиться с поведением route-level гейта.

        Args:
            name: Имя feature-флага (позиционная форма).
            flag: Имя feature-флага (именованная форма). Дублирует ``name``.
            default: Значение флага, если он не найден в registry.
            stop_on_disabled: Останавливать ли pipeline при выключенном флаге.
            output_field: Имя поля результата пошаговой проверки.

        Returns:
            ``self`` — для fluent-цепочки.

        Raises:
            ValueError: Если не передан ни ``name``, ни ``flag``, либо
                переданы оба с разными значениями.

        """
        resolved = name if name is not None else flag
        if resolved is None:
            raise ValueError("feature_flag требует имя флага: name= или flag=")
        if name is not None and flag is not None and name != flag:
            raise ValueError(
                f"feature_flag получил разные имена: name={name!r}, flag={flag!r}"
            )
        self._feature_flag = resolved
        self._feature_flag_default = default
        self._feature_flag_stop_on_disabled = stop_on_disabled
        self._feature_flag_output_field = output_field
        return self

    def shadow_mode(self, processors: list[BaseProcessor]) -> Self:
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
    ) -> Self:
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
    ) -> Self:
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
