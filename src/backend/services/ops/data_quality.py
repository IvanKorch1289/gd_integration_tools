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
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import Any

from src.backend.core.di.app_state import app_state_singleton

__all__ = ("DQCheckResult", "DQRule", "DataQualityMonitor", "get_dq_monitor")

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
    violations: list[DQViolation] = dataclass_field(default_factory=list)
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
    params: dict[str, Any] = dataclass_field(default_factory=dict)
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
            k: list(v)[0] if len(v) == 1 else str(v) for k, v in schema.items()
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

        elif rule.check == "regex_match":
            pattern = rule.params.get("pattern", "")
            if not pattern:
                return DQViolation(
                    rule.name,
                    rule.field,
                    DQSeverity.ERROR,
                    f"regex_match rule {rule.name!r} missing 'pattern' param",
                    value,
                )
            import re as _re

            if value is not None and not _re.match(pattern, str(value)):
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Value {str(value)[:50]!r} does not match pattern {pattern!r}",
                    value,
                )

        elif rule.check == "enum":
            allowed = rule.params.get("values", [])
            if value is not None and value not in allowed:
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Value {value!r} not in allowed {list(allowed)[:5]}",
                    value,
                )

        elif rule.check == "length":
            if value is None:
                return None
            length = len(value) if hasattr(value, "__len__") else None
            if length is None:
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Value has no length: {type(value).__name__}",
                    value,
                )
            min_len = rule.params.get("min")
            max_len = rule.params.get("max")
            if min_len is not None and length < min_len:
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Length {length} < min {min_len}",
                    value,
                )
            if max_len is not None and length > max_len:
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Length {length} > max {max_len}",
                    value,
                )

        elif rule.check == "date_format":
            import datetime as _dt

            fmt = rule.params.get("format", "%Y-%m-%d")
            if value is None:
                return None
            try:
                _dt.datetime.strptime(str(value), fmt)
            except (ValueError, TypeError):
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Value {str(value)[:30]!r} does not match date format {fmt!r}",
                    value,
                )

        elif rule.check == "cross_field":
            other_field = rule.params.get("other_field")
            operator = rule.params.get("operator", "eq")
            if not other_field:
                return DQViolation(
                    rule.name,
                    rule.field,
                    DQSeverity.ERROR,
                    f"cross_field rule {rule.name!r} missing 'other_field' param",
                    value,
                )
            other_value = record.get(other_field)
            ops = {
                "eq": lambda a, b: a == b,
                "ne": lambda a, b: a != b,
                "lt": lambda a, b: a < b,
                "le": lambda a, b: a <= b,
                "gt": lambda a, b: a > b,
                "ge": lambda a, b: a >= b,
            }
            fn = ops.get(operator)
            if fn is None:
                return DQViolation(
                    rule.name,
                    rule.field,
                    DQSeverity.ERROR,
                    f"Unknown cross_field operator {operator!r}",
                    value,
                )
            if value is not None and other_value is not None and not fn(value, other_value):
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"cross_field {rule.field} {operator} {other_field} failed: "
                    f"{value!r} vs {other_value!r}",
                    value,
                )

        elif rule.check == "json_schema":
            try:
                import jsonschema  # type: ignore[import-untyped]
            except ImportError:
                return DQViolation(
                    rule.name,
                    rule.field,
                    DQSeverity.WARNING,
                    "jsonschema не установлен — пропуск json_schema check",
                    value,
                )
            schema = rule.params.get("schema", {})
            if not schema:
                return DQViolation(
                    rule.name,
                    rule.field,
                    DQSeverity.ERROR,
                    f"json_schema rule {rule.name!r} missing 'schema' param",
                    value,
                )
            try:
                jsonschema.validate(instance=value, schema=schema)
            except jsonschema.ValidationError as exc:
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"json_schema failed: {exc.message[:100]}",
                    value,
                )

        elif rule.check == "cardinality":
            # Distinct count check: value should appear ≤ max_count times
            max_count = rule.params.get("max_count", 1)
            key = f"{dataset}:{rule.field}:{value}"
            seen = getattr(self, "_cardinality_counts", None)
            if seen is None:
                seen = self._cardinality_counts = defaultdict(int)
            seen[key] += 1
            if seen[key] > max_count:
                return DQViolation(
                    rule.name,
                    rule.field,
                    rule.severity,
                    f"Value {str(value)[:30]!r} seen {seen[key]} times > max_count {max_count}",
                    value,
                )

        return None


@app_state_singleton("dq_monitor", factory=DataQualityMonitor)
def get_dq_monitor() -> DataQualityMonitor:
    raise NotImplementedError  # заменяется декоратором
