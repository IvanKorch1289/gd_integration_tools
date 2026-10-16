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


from src.backend.dsl.engine.processors import (
    LogProcessor,
    SetPropertyProcessor,
    ValidateProcessor,
)


class ValidationMixin(_RouteBuilderProtocol):
    """logging + validation + property setters для RouteBuilder. S57 W1 extraction."""

    __slots__ = ()

    def set_property(self, key: str, value: Any) -> Self:
        """Устанавливает runtime-свойство Exchange."""
        return self._add(SetPropertyProcessor(key=key, value=value))

    def log(self, level: str = "info") -> Self:
        """Логирование текущего состояния Exchange (для отладки)."""
        return self._add(LogProcessor(level=level))

    def validate(self, model: type) -> Self:
        """Pydantic-валидация body; при ошибке Exchange останавливается."""
        return self._add(ValidateProcessor(model=model))

    def _validate_action_names(self) -> None:
        """DX-1: проверяет что все dispatch_action имена зарегистрированы.

        Raises ValueError с подсказкой схожих имён при опечатке.
        Вызывается в .build() (можно отключить validate_actions=False).
        """
        try:
            from src.backend.dsl.commands.registry import action_handler_registry

            available = set(action_handler_registry.list_actions())
        except (ImportError, AttributeError):
            return

        if not available:
            return

        action_names: list[str] = []
        for proc in self._processors:
            if type(proc).__name__ == "DispatchActionProcessor":
                action = getattr(proc, "action", None)
                if action and isinstance(action, str):
                    action_names.append(action)

        unknown = [name for name in action_names if name not in available]
        if not unknown:
            return

        import difflib

        suggestions: dict[str, list[str]] = {}
        for name in unknown:
            close = difflib.get_close_matches(name, available, n=3, cutoff=0.6)
            if close:
                suggestions[name] = close

        msg_parts = [f"Unknown action(s) in pipeline '{self.route_id}':"]
        for name in unknown:
            suggestion = suggestions.get(name)
            if suggestion:
                msg_parts.append(
                    f"  - '{name}' — did you mean: {', '.join(suggestion)}?"
                )
            else:
                msg_parts.append(f"  - '{name}'")
        raise ValueError("\n".join(msg_parts))
