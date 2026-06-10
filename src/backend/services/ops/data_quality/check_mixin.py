from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # cross-mixin / state attrs declared below

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

import statistics
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import Any

from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.logging import get_logger

logger = get_logger(__name__)

class DQSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

@dataclass(slots=True)
class DQViolation:
    rule: str
    field: str
    severity: DQSeverity
    message: str
    value: Any = None

@dataclass(slots=True)
class DQCheckResult:
    violations: list[DQViolation] = dataclass_field(default_factory=list)
    passed: int = 0
    failed: int = 0

    @property
    def is_clean(self) -> bool:
        return len(self.violations) == 0

@dataclass(slots=True)
class DQRemediationResult:
    """Result of auto-remediation pass.

    Attributes:
        data: remediated data (same shape as input: dict или list of dicts).
        violations: list of violations detected (до remediation).
        fixes_applied: number of values that were actually changed.
    """

    data: Any
    violations: list[DQViolation] = dataclass_field(default_factory=list)
    fixes_applied: int = 0

    @property
    def is_clean(self) -> bool:
        return len(self.violations) == 0

@dataclass(slots=True)
class DQRule:
    """Правило проверки качества данных."""

    name: str
    field: str
    check: str  # "not_null", "type", "range", "unique", "regex"
    params: dict[str, Any] = dataclass_field(default_factory=dict)
    severity: DQSeverity = DQSeverity.WARNING
    enabled: bool = True

class CheckMixin:
    """capability check (check, _check_rule) для DataQualityMonitor. S55 W4 extraction."""

    __slots__ = ()

    def _check_rule(self, rule: DQRule, value: Any, dataset: str) -> list[DQViolation]:
        """Check single rule against single value. Returns violations (may be empty)."""
        # Reuse the existing check logic by running through the full check path.
        # For simplicity we re-use monitor.check() per record — but to avoid
        # double work, we run a focused check inline.
        violations: list[DQViolation] = []
        # not_null
        if rule.check == "not_null" and (value is None or value == ""):
            violations.append(
                DQViolation(
                    rule=rule.name,
                    field=rule.field,
                    severity=rule.severity,
                    message=f"Field {rule.field!r} is null/empty (value={value!r})",
                    value=value,
                )
            )
        # range
        elif (
            rule.check == "range"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            lo = rule.params.get("min")
            hi = rule.params.get("max")
            if (lo is not None and value < lo) or (hi is not None and value > hi):
                violations.append(
                    DQViolation(
                        rule=rule.name,
                        field=rule.field,
                        severity=rule.severity,
                        message=f"Value {value!r} out of range [{lo}, {hi}]",
                        value=value,
                    )
                )
        # regex
        elif rule.check == "regex" and isinstance(value, str):
            import re as _re

            pattern = rule.params.get("pattern")
            if pattern and not _re.match(pattern, value):
                violations.append(
                    DQViolation(
                        rule=rule.name,
                        field=rule.field,
                        severity=rule.severity,
                        message=f"Value {value!r} does not match pattern {pattern!r}",
                        value=value,
                    )
                )
        # enum
        elif rule.check == "enum":
            allowed = rule.params.get("allowed", [])
            if allowed and value not in allowed:
                violations.append(
                    DQViolation(
                        rule=rule.name,
                        field=rule.field,
                        severity=rule.severity,
                        message=f"Value {value!r} not in allowed {allowed!r}",
                        value=value,
                    )
                )
        # type
        elif rule.check == "type" and value is not None:
            expected = rule.params.get("expected_type")
            type_map = {"int": int, "float": float, "str": str, "bool": bool}
            expected_py = type_map.get(expected or "")
            if expected_py and not isinstance(value, expected_py):
                # allow int for float
                if not (expected_py is float and isinstance(value, int)):
                    violations.append(
                        DQViolation(
                            rule=rule.name,
                            field=rule.field,
                            severity=rule.severity,
                            message=f"Value {value!r} is not {expected}",
                            value=value,
                        )
                    )
        return violations

    async def check(
        self, data: dict[str, Any] | list[dict[str, Any]], dataset: str = "default"
    ) -> dict[str, Any]:
        """Проверяет данные по правилам."""
        records = data if isinstance(data, list) else [data]
        result = DQCheckResult()

        for record in records:
            for rule in self._rules:
                if not rule.enabled:
                    continue
                violation = self._apply_rule(rule, record, dataset)
                if violation:
                    result.violations.append(violation)
                    result.failed += 1
                else:
                    result.passed += 1

        self._stats[dataset]["checks"] += result.passed + result.failed
        self._stats[dataset]["violations"] += result.failed

        return {
            "is_clean": result.is_clean,
            "passed": result.passed,
            "failed": result.failed,
            "violations": [
                {
                    "rule": v.rule,
                    "field": v.field,
                    "severity": v.severity.value,
                    "message": v.message,
                    "value": v.value,
                }
                for v in result.violations
            ],
        }

