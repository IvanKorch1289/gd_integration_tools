from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # cycle-8/D-AUDIT-803: canonical DQ types live in __init__.py
    from src.backend.services.ops.data_quality import DQCheckResult, DQRule, DQSeverity, DQViolation

"""Data Quality Monitor — авто-детект схемы + аномалии.

Проверки:
- Missing required fields (NULL/empty)
- Type violations (string in numeric field)
- Outliers (Z-score > 3σ)
- Duplicate records (same PK within window)
- Late-arriving data (> threshold old)
- Schema drift (новые/удалённые поля)

Actions: dq.check, dq.schema_infer, dq.stats, dq.rules

cycle-8/D-AUDIT-803: DQSeverity/DQViolation/DQCheckResult/DQRule consolidated
в __init__.py (canonical). Здесь только runtime use через post-load injection
(см. __init__.py).
"""


from src.backend.services.ops.data_quality._protocol import _DataQualityProtocol


class CheckMixin(_DataQualityProtocol):
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
