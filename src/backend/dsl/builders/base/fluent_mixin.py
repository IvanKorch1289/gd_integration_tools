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


from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    BaseProcessor,
    CallableProcessor,
    ProcessorCallable,
)


class FluentMixin:
    """fluent chaining (to, process_fn, include + internal helpers) для RouteBuilder. S57 W1 extraction."""

    __slots__ = ()

    def to(self, processor: BaseProcessor) -> RouteBuilder:
        """Алиас для process() — fluent naming."""
        return self._add(processor)

    def process_fn(
        self, func: ProcessorCallable, *, name: str | None = None
    ) -> RouteBuilder:
        """Добавляет обычную функцию или coroutine как процессор.

        Функция принимает (exchange, context) и модифицирует exchange in-place.
        """
        return self._add(CallableProcessor(func=func, name=name))

    def include(self, other: Pipeline) -> RouteBuilder:
        """Включает все процессоры из другого Pipeline (композиция)."""
        self._processors.extend(other.processors)
        return self

    def _last_processor_or_raise(self) -> BaseProcessor:
        """Возвращает последний добавленный processor для chainable-модификации.

        Raises:
            ValueError: если pipeline пуст — модификатор вызван до первого step.
        """
        if not self._processors:
            raise ValueError(
                "with_*-модификатор вызван до первого step — нет предыдущего "
                "processor для модификации"
            )
        return self._processors[-1]

    @staticmethod
    def _set_first_attr(
        obj: Any, candidates: tuple[str, ...], value: Any
    ) -> str | None:
        """Устанавливает значение в первый из существующих candidate-атрибутов."""
        for attr in candidates:
            if hasattr(obj, attr):
                setattr(obj, attr, value)
                return attr
        return None
