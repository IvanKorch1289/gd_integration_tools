from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.services.ops.data_quality import DQRemediationResult

"""Data Quality Monitor — авто-детект схемы + аномалии.

Проверки:
- Missing required fields (NULL/empty)
- Type violations (string in numeric field)
- Outliers (Z-score > 3σ)
- Duplicate records (same PK within window)
- Late-arriving data (> threshold old)
- Schema drift (новые/удалённые поля)

Actions: dq.check, dq.schema_infer, dq.stats, dq.rules
"""

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum

from src.backend.core.logging import get_logger

logger = get_logger(__name__)


class DQSeverity(str, Enum):
    """Data quality violation severity levels."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(slots=True)
class DQViolation:
    """Data quality violation record."""
    rule: str
    field: str
    severity: DQSeverity
    message: str
    value: Any = None


@dataclass(slots=True)
class DQCheckResult:
    """Data quality check result."""
    violations: list[DQViolation] = dataclass_field(default_factory=list)
    passed: int = 0
    failed: int = 0

    @property
    def is_clean(self) -> bool:
        """Check if no violations found.

        Returns:
            True if no violations.
        """
        return len(self.violations) == 0


# DQRemediationResult lives in __init__.py (S153 W1: 5x dedup)
@dataclass(slots=True)
class DQRule:
    """Правило проверки качества данных."""

    name: str
    field: str
    check: str  # "not_null", "type", "range", "unique", "regex"
    params: dict[str, Any] = dataclass_field(default_factory=dict)
    severity: DQSeverity = DQSeverity.WARNING
    enabled: bool = True


from src.backend.services.ops.data_quality._protocol import _DataQualityProtocol


class RuleManagementMixin(_DataQualityProtocol):
    """rule management (add_rules, list_rules, remediate) для DataQualityMonitor. S55 W4 extraction."""

    __slots__ = ()

    def add_rules(self, rules: list[DQRule]) -> None:
        """Add data quality rules.

        Args:
            rules: List of DQRule objects to add.
        """
        self._rules.extend(rules)

    def list_rules(self) -> list[dict[str, Any]]:
        return [
            {
                "name": r.name,
                "field": r.field,
                "check": r.check,
                "severity": r.severity.value,
                "enabled": r.enabled,
            }
            for r in self._rules
        ]

    def remediate(
        self, data: dict[str, Any] | list[dict[str, Any]], *, dataset: str = "default"
    ) -> DQRemediationResult:
        """Detect violations и apply auto-remediation per configured rules.

        Для каждой rule (check type) с подходящим remediator — применяет fix
        и инкрементит ``fixes_applied``. Violations остаются в результате для
        observability (после remediation данные могут быть валидны, но факт
        violation полезно логировать).

        Supported remediation strategies (см. ``dq_remediation.py``):
        * not_null → NullDefaultRemediator
        * range → RangeClipRemediator
        * regex → RegexMaskRemediator
        * enum → EnumFallbackRemediator
        * type → TypeCoerceRemediator

        Args:
            data: dict или list of dicts для remediation.
            dataset: имя dataset (для logging).

        Returns:
            DQRemediationResult с remediated data, list of detected violations,
            и counter применённых fixes.
        """
        from src.backend.services.ops.data_quality import DQRemediationResult
        from src.backend.services.ops.dq_remediation import build_remediator

        records = data if isinstance(data, list) else [data]
        all_violations: list[DQViolation] = []
        total_fixes = 0

        # Detect violations по rules (для observability)
        for rule in self._rules:
            if not rule.enabled:
                continue
            for record in records:
                field_value = (
                    record.get(rule.field) if isinstance(record, dict) else None
                )
                violations = self._check_rule(rule, field_value, dataset)
                all_violations.extend(violations)

        # Apply remediation per rule
        remediated_records: list[Any] = []
        for record in records:
            if not isinstance(record, dict):
                remediated_records.append(record)
                continue
            new_record = dict(record)
            for rule in self._rules:
                if not rule.enabled:
                    continue
                if rule.field not in new_record:
                    continue
                remediator = build_remediator(rule.check, rule.params)
                if remediator is None:
                    continue
                old_value = new_record[rule.field]
                new_value = remediator.remediate(old_value, rule.params)
                if new_value != old_value:
                    new_record[rule.field] = new_value
                    total_fixes += 1
                    logger.info(
                        "DQ auto-remediation: rule=%s field=%s %r → %r",
                        rule.name,
                        rule.field,
                        old_value,
                        new_value,
                    )
            remediated_records.append(new_record)

        result_data = (
            remediated_records if isinstance(data, list) else remediated_records[0]
        )
        return DQRemediationResult(  # type: ignore[arg-type]
            data=result_data, violations=all_violations, fixes_applied=total_fixes
        )
