from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

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


class ComplianceMixin:
    """multi-tenant + compliance (tenant_scope, mask, compliance_labels, lineage) для RouteBuilder. S57 W1 extraction."""

    __slots__ = ()

    def lineage(self, tag: str = "step") -> RouteBuilder:
        """Записывает шаг в `_lineage` property (data governance)."""
        from src.backend.dsl.engine.processors.generic import LineageTrackerProcessor

        return self._add(LineageTrackerProcessor(tag=tag))

    def tenant_scope(
        self,
        *,
        header: str = "x-tenant-id",
        body_path: str | None = None,
        required: bool = True,
    ) -> RouteBuilder:
        """Multi-tenancy scope: tenant_id из заголовка/body в Exchange."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "TenantScopeProcessor",
            header=header,
            body_path=body_path,
            required=required,
        )

    def mask(
        self, *, patterns: list[str] | None = None, replacement: str = "***"
    ) -> RouteBuilder:
        """Маскирование PII/PCI в body (ИНН/СНИЛС/карта/email/телефон)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "DataMaskingProcessor",
            patterns=patterns,
            replacement=replacement,
        )

    def compliance_labels(self, *, labels: list[str]) -> RouteBuilder:
        """Compliance-метки на Exchange (PII/PCI/FIN/GDPR)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "ComplianceLabelProcessor",
            labels=labels,
        )
