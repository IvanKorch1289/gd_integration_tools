"""Base-модуль RouteBuilder.

Содержит сам класс ``RouteBuilder`` (``@dataclass(slots=True)``) и
``BaseMixin`` с core-методами + chainable modifiers + observability hooks.

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
* приватные утилиты (``_add``, ``_last_processor_or_raise``,
  ``_set_first_attr``, ``_validate_action_names``) живут на
  ``RouteBuilder`` и доступны через ``self``.

Этот файл будет окончательно заполнен на Stage 2.6 — туда переедут
core-методы из ``src/backend/dsl/builder.py``.
"""

from __future__ import annotations


class BaseMixin:
    """Core: from_/process/to/log/build + chainable modifiers + observability.

    Stage 1 placeholder (см. /home/user/.claude/plans/replicated-seeking-panda.md).
    Методы перенесутся из ``src/backend/dsl/builder.py`` в Stage 2.6.
    """

    __slots__ = ()  # type: ignore[var-annotated]
