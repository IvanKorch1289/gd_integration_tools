"""Structural protocol for DataQualityMonitor mixins.

Sprint 36 (tech-debt): объявляет cross-mixin атрибуты и методы, чтобы
mypy видел ``self._rules``, ``self._apply_rule`` и т.д. внутри миксинов.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.backend.services.ops.data_quality.check_mixin import DQRule, DQViolation


class _DataQualityProtocol(Protocol):
    """Общий контракт для RuleManagementMixin / CheckMixin / SchemaMixin / ApplyMixin."""

    _rules: list[DQRule]
    _inferred_schemas: dict[str, dict[str, str]]
    _stats: dict[str, dict[str, Any]]
    _seen_keys: dict[str, set[str]]
    _numeric_history: dict[str, list[float]]

    def add_rule(self, rule: DQRule) -> None: ...

    def add_rules(self, rules: list[DQRule]) -> None: ...

    def list_rules(self) -> list[dict[str, Any]]: ...

    def _check_rule(
        self, rule: DQRule, value: Any, dataset: str
    ) -> list[DQViolation]: ...

    def _apply_rule(
        self, rule: DQRule, record: dict[str, Any], dataset: str
    ) -> DQViolation | None: ...
