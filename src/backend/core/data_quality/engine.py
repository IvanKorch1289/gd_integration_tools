"""Data Quality Engine — pure-Python implementation (Wave 4 #35)."""

from __future__ import annotations

import enum
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "DataQualityEngine",
    "QualityReport",
    "QualityRule",
    "QualityViolation",
    "RuleKind",
    "RuleSet",
    "get_data_quality_engine",
)


class RuleKind(str, enum.Enum):
    """Type of quality rule."""

    NON_NULL = "non_null"  # field must not be None
    NON_EMPTY = "non_empty"  # field must not be empty string/list/dict
    UNIQUE = "unique"  # field must be unique across records
    RANGE = "range"  # numeric field must be in [min, max]
    FORMAT = "format"  # string field must match regex
    ENUM = "enum"  # field must be in allowed values
    REFERENCE = "reference"  # field must exist in foreign key table
    CUSTOM = "custom"  # custom callable


@dataclass(slots=True)
class QualityRule:
    """Single quality rule.

    Attributes:
        field: Field name to check (or "*" for whole record).
        kind: Type of check.
        min: Min value (for RANGE).
        max: Max value (for RANGE).
        regex: Regex pattern (for FORMAT).
        allowed: Allowed values (for ENUM).
        custom_fn: Custom callable (for CUSTOM).
        error_message: Custom error message.
    """

    field: str
    kind: RuleKind
    min: float | None = None
    max: float | None = None
    regex: str | None = None
    allowed: tuple[Any, ...] = ()
    custom_fn: Any = None
    error_message: str = ""


@dataclass(slots=True)
class RuleSet:
    """Набор правил для record type."""

    record_type: str
    rules: list[QualityRule] = field(default_factory=list)
    quarantine_on_failure: bool = True


@dataclass(slots=True)
class QualityViolation:
    """Single rule violation."""

    record_type: str
    field: str
    rule_kind: RuleKind
    record: Any
    expected: Any = None
    actual: Any = None
    reason: str = ""


@dataclass(slots=True)
class QualityReport:
    """Quality check report."""

    record_type: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    violations: list[QualityViolation] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total > 0 else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "violations": [
                {
                    "field": v.field,
                    "rule_kind": v.rule_kind.value,
                    "reason": v.reason,
                    "actual": str(v.actual)[:100],
                }
                for v in self.violations
            ],
        }


class DataQualityEngine:
    """Registry + executor for quality rules."""

    def __init__(self) -> None:
        self._rulesets: dict[str, RuleSet] = {}
        self._quarantine: list[tuple[Any, str]] = []  # (record, reason)
        # Track unique values for UNIQUE rule.
        self._unique_trackers: dict[tuple[str, str], set] = defaultdict(set)

    def register(self, ruleset: RuleSet) -> None:
        """Register a ruleset for a record type."""
        self._rulesets[ruleset.record_type] = ruleset

    def get(self, record_type: str) -> RuleSet | None:
        """Get ruleset for record type."""
        return self._rulesets.get(record_type)

    def list_record_types(self) -> list[str]:
        """List all registered record types."""
        return list(self._rulesets.keys())

    def check(
        self, record_type: str, records: list[Any]
    ) -> QualityReport:
        """Check records against registered rules.

        Args:
            record_type: Type identifier.
            records: List of records (dicts).

        Returns:
            :class:`QualityReport` with pass/fail + violations.
        """
        report = QualityReport(record_type=record_type, total=len(records))
        ruleset = self._rulesets.get(record_type)
        if ruleset is None:
            logger.warning("No ruleset for record_type=%s", record_type)
            report.passed = len(records)
            return report

        # Reset unique trackers for this check.
        unique_trackers: dict[tuple[str, str], set] = defaultdict(set)

        for record in records:
            record_passed = True
            for rule in ruleset.rules:
                violation = self._check_rule(rule, record, unique_trackers)
                if violation is not None:
                    report.violations.append(violation)
                    record_passed = False
            if record_passed:
                report.passed += 1
            else:
                report.failed += 1
                if ruleset.quarantine_on_failure:
                    reasons = "; ".join(
                        v.reason for v in report.violations
                        if v.record is record
                    )
                    self.quarantine(record, reasons)
        return report

    def _check_rule(
        self,
        rule: QualityRule,
        record: Any,
        unique_trackers: dict[tuple[str, str], set],
    ) -> QualityViolation | None:
        """Check a single rule against a record."""
        if rule.kind == RuleKind.NON_NULL:
            value = self._get_field(record, rule.field)
            if value is None:
                return QualityViolation(
                    record_type=getattr(record, "__rule_type__", ""),
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected="not None",
                    actual=value,
                    reason=rule.error_message or f"{rule.field} is null",
                )
            return None

        if rule.kind == RuleKind.NON_EMPTY:
            value = self._get_field(record, rule.field)
            if not value:  # None, empty string, empty list/dict
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected="non-empty",
                    actual=value,
                    reason=rule.error_message or f"{rule.field} is empty",
                )
            return None

        if rule.kind == RuleKind.UNIQUE:
            value = self._get_field(record, rule.field)
            if value is None:
                return None
            key = (self._get_type_key(record), rule.field)
            if value in unique_trackers[key]:
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected="unique",
                    actual=value,
                    reason=f"duplicate {rule.field}={value}",
                )
            unique_trackers[key].add(value)
            return None

        if rule.kind == RuleKind.RANGE:
            value = self._get_field(record, rule.field)
            if value is None:
                return None
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected="numeric",
                    actual=value,
                    reason=f"{rule.field} not numeric",
                )
            if rule.min is not None and value < rule.min:
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected=f">= {rule.min}",
                    actual=value,
                    reason=f"{rule.field}={value} < {rule.min}",
                )
            if rule.max is not None and value > rule.max:
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected=f"<= {rule.max}",
                    actual=value,
                    reason=f"{rule.field}={value} > {rule.max}",
                )
            return None

        if rule.kind == RuleKind.FORMAT:
            value = self._get_field(record, rule.field)
            if value is None:
                return None
            if not isinstance(value, str) or not re.match(rule.regex or "", value):
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected=f"matches {rule.regex}",
                    actual=value,
                    reason=f"{rule.field}={value!r} doesn't match pattern",
                )
            return None

        if rule.kind == RuleKind.ENUM:
            value = self._get_field(record, rule.field)
            if value is None:
                return None
            if value not in rule.allowed:
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected=f"in {rule.allowed}",
                    actual=value,
                    reason=f"{rule.field}={value!r} not in allowed",
                )
            return None

        if rule.kind == RuleKind.CUSTOM and rule.custom_fn is not None:
            try:
                result = rule.custom_fn(record)
            except Exception as exc:
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected="custom pass",
                    actual=None,
                    reason=f"custom raised: {exc}",
                )
            if not result:
                return QualityViolation(
                    record_type="",
                    field=rule.field,
                    rule_kind=rule.kind,
                    record=record,
                    expected="custom pass",
                    actual=None,
                    reason=rule.error_message or "custom returned False",
                )
        return None

    def _get_field(self, record: Any, field: str) -> Any:
        """Get field value from dict или object."""
        if isinstance(record, dict):
            return record.get(field)
        return getattr(record, field, None)

    def _get_type_key(self, record: Any) -> str:
        """Type identifier for unique tracking."""
        if isinstance(record, dict):
            return record.get("_type", "default")
        return type(record).__name__

    def quarantine(self, record: Any, reason: str) -> None:
        """Add record к quarantine list."""
        self._quarantine.append((record, reason))

    def get_quarantine(self) -> list[tuple[Any, str]]:
        """Get quarantined records (record, reason)."""
        return list(self._quarantine)

    def clear_quarantine(self) -> None:
        self._quarantine.clear()

    def quarantine_size(self) -> int:
        return len(self._quarantine)


_engine: DataQualityEngine | None = None


def get_data_quality_engine() -> DataQualityEngine:
    global _engine
    if _engine is None:
        _engine = DataQualityEngine()
    return _engine


def reset_data_quality_engine() -> None:
    global _engine
    _engine = None
