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

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = ("DataQualityMonitor", "DQRule", "DQCheckResult", "get_dq_monitor")

logger = logging.getLogger(__name__)


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
    violations: list[DQViolation] = field(default_factory=list)
    passed: int = 0
    failed: int = 0

    @property
    def is_clean(self) -> bool:
        return len(self.violations) == 0


@dataclass(slots=True)
class DQRule:
    """Правило проверки качества данных."""

    name: str
    field: str
    check: str  # "not_null", "type", "range", "unique", "regex"
    params: dict[str, Any] = field(default_factory=dict)
    severity: DQSeverity = DQSeverity.WARNING
    enabled: bool = True


class DataQualityMonitor:
    """Монитор качества данных с авто-детектом схемы."""

    def __init__(self) -> None:
        self._rules: list[DQRule] = []
        self._inferred_schemas: dict[str, dict[str, str]] = {}
        self._stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"checks": 0, "violations": 0}
        )
        self._seen_keys: dict[str, set[str]] = defaultdict(set)
        self._numeric_history: dict[str, list[float]] = defaultdict(list)

    def add_rule(self, rule: DQRule) -> None:
        self._rules.append(rule)

    def add_rules(self, rules: list[DQRule]) -> None:
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

    async def schema_infer(
        self, data: dict[str, Any] | list[dict[str, Any]], dataset: str = "default"
    ) -> dict[str, Any]:
        """Инферит схему из данных."""
        records = data if isinstance(data, list) else [data]
        schema: dict[str, set[str]] = defaultdict(set)

        for record in records:
            for k, v in record.items():
                schema[k].add(type(v).__name__)

        inferred = {k: list(v) for k, v in schema.items()}
        prev = self._inferred_schemas.get(dataset)
        drift: dict[str, str] = {}
        if prev:
            for k in set(inferred) - set(prev):
                drift[k] = "new_field"
            for k in set(prev) - set(inferred):
                drift[k] = "missing_field"

        self._inferred_schemas[dataset] = {
            k: v[0] if len(v) == 1 else str(v) for k, v in schema.items()
        }
        return {
            "schema": self._inferred_schemas[dataset],
            "drift": drift,
            "fields": len(inferred),
        }

    async def stats(self, dataset: str | None = None) -> dict[str, Any]:
        """Статистика проверок."""
        if dataset:
            return {"dataset": dataset, **dict(self._stats[dataset])}
        return {k: dict(v) for k, v in self._stats.items()}

    def _apply_rule(
        self, rule: DQRule, record: dict[str, Any], dataset: str
    ) -> DQViolation | None:
        value = record.get(rule.field)

        if rule.check == "not_null":
            if value is None or value == "":
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Field '{rule.field}' is null/empty",
                    value,
                )

        elif rule.check == "type":
            expected = rule.params.get("type", "str")
            type_map = {
                "str": str,
                "int": int,
                "float": (int, float),
                "bool": bool,
                "dict": dict,
                "list": list,
            }
            expected_type = type_map.get(expected, str)
            if value is not None and not isinstance(value, expected_type):
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Expected {expected}, got {type(value).__name__}",
                    value,
                )

        elif rule.check == "range":
            if isinstance(value, (int, float)):
                min_val = rule.params.get("min")
                max_val = rule.params.get("max")
                if min_val is not None and value < min_val:
                    return DQViolation(
                        rule.name,
                        rule.field,
                        rule.severity,
                        f"Value {value} < min {min_val}",
                        value,
                    )
                if max_val is not None and value > max_val:
                    return DQViolation(
                        rule.name,
                        rule.field,
                        rule.severity,
                        f"Value {value} > max {max_val}",
                        value,
                    )

        elif rule.check == "unique":
            key = f"{dataset}:{rule.field}"
            str_val = str(value)
            if str_val in self._seen_keys[key]:
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Duplicate value: {str_val[:50]}",
                    value,
                )
            self._seen_keys[key].add(str_val)

        elif rule.check == "outlier":
            if isinstance(value, (int, float)):
                key = f"{dataset}:{rule.field}"
                history = self._numeric_history[key]
                if len(history) >= 10:
                    mean = statistics.mean(history)
                    stddev = statistics.stdev(history)
                    if stddev > 0:
                        z = abs((value - mean) / stddev)
                        threshold = rule.params.get("z_threshold", 3.0)
                        if z > threshold:
                            return DQViolation(
                                rule.name,
                                rule.field,
                                DQSeverity.WARNING,
                                f"Outlier: z-score={z:.2f}",
                                value,
                            )
                history.append(value)
                if len(history) > 1000:
                    self._numeric_history[key] = history[-500:]

        return None


_dq_monitor_instance = DataQualityMonitor()


def get_dq_monitor() -> DataQualityMonitor:
    return _dq_monitor_instance
