from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass  # cross-mixin / state attrs declared below

import statistics
from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum

from src.backend.core.logging import get_logger

logger = get_logger(__name__)

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


class ApplyMixin(_DataQualityProtocol):
    """rule application (_apply_rule — the BIG method, 263 LOC) для DataQualityMonitor. S55 W4 extraction."""

    __slots__ = ()

    # ─── Helpers per check type ───────────────────────────────────────

    def _apply_not_null(self, rule: DQRule, value: Any) -> DQViolation | None:
        """Return violation if value is None or empty string."""
        if value is None or value == "":
            return DQViolation(
                rule.name,
                rule.field,
                rule.severity,
                f"Field '{rule.field}' is null/empty",
                value,
            )
        return None

    def _apply_type(self, rule: DQRule, value: Any) -> DQViolation | None:
        """Return violation if value type does not match expected type."""
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
        return None

    def _apply_range(self, rule: DQRule, value: Any) -> DQViolation | None:
        """Return violation if numeric value is outside [min, max]."""
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
        return None

    def _apply_unique(
        self, rule: DQRule, value: Any, dataset: str
    ) -> DQViolation | None:
        """Return violation if value was already seen in the same dataset/field."""
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
        return None

    def _apply_outlier(
        self, rule: DQRule, value: Any, dataset: str
    ) -> DQViolation | None:
        """Return violation if numeric value is a statistical outlier (z-score)."""
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

    def _apply_regex_match(self, rule: DQRule, value: Any) -> DQViolation | None:
        """Return violation if value does not match the configured regex pattern."""
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
        return None

    def _apply_enum(self, rule: DQRule, value: Any) -> DQViolation | None:
        """Return violation if value is not in the allowed list."""
        allowed = rule.params.get("values", [])
        if value is not None and value not in allowed:
            return DQViolation(
                rule.name,
                rule.field,
                rule.severity,
                f"Value {value!r} not in allowed {list(allowed)[:5]}",
                value,
            )
        return None

    def _apply_length(self, rule: DQRule, value: Any) -> DQViolation | None:
        """Return violation if value length is outside [min, max]."""
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
        return None

    def _apply_date_format(self, rule: DQRule, value: Any) -> DQViolation | None:
        """Return violation if value does not match the expected date format."""
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
        return None

    def _apply_cross_field(
        self, rule: DQRule, value: Any, record: dict[str, Any]
    ) -> DQViolation | None:
        """Return violation if cross-field comparison fails."""
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
        return None

    def _apply_json_schema(self, rule: DQRule, value: Any) -> DQViolation | None:
        """Return violation if value fails jsonschema validation."""
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
        return None

    def _apply_cardinality(
        self, rule: DQRule, value: Any, dataset: str
    ) -> DQViolation | None:
        """Return violation if value appears more than max_count times."""
        max_count = rule.params.get("max_count", 1)
        key = f"{dataset}:{rule.field}:{value}"
        seen: defaultdict[str, int] = getattr(self, "_cardinality_counts", None)  # type: ignore[assignment]
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

    # ─── Public dispatcher ────────────────────────────────────────────

    def _apply_rule(
        self, rule: DQRule, record: dict[str, Any], dataset: str
    ) -> DQViolation | None:
        """Dispatch to the appropriate check-specific helper."""
        value = record.get(rule.field)

        match rule.check:
            case "not_null":
                return self._apply_not_null(rule, value)
            case "type":
                return self._apply_type(rule, value)
            case "range":
                return self._apply_range(rule, value)
            case "unique":
                return self._apply_unique(rule, value, dataset)
            case "outlier":
                return self._apply_outlier(rule, value, dataset)
            case "regex_match":
                return self._apply_regex_match(rule, value)
            case "enum":
                return self._apply_enum(rule, value)
            case "length":
                return self._apply_length(rule, value)
            case "date_format":
                return self._apply_date_format(rule, value)
            case "cross_field":
                return self._apply_cross_field(rule, value, record)
            case "json_schema":
                return self._apply_json_schema(rule, value)
            case "cardinality":
                return self._apply_cardinality(rule, value, dataset)
            case _:
                return None
