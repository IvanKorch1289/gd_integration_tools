"""DataQualityMonitor package (S55 W4 decomp from data_quality.py 618 LOC).

10 methods decomposed в 4 mixin files:
- ``rule_mgmt_mixin.py`` (3): add_rules, list_rules, remediate
- ``check_mixin.py`` (2): check, _check_rule
- ``schema_mixin.py`` (2): schema_infer, stats
- ``apply_mixin.py`` (1): _apply_rule (the BIG one, 263 LOC)

Core (__init__ + add_rule) остается в __init__.py.

Backward-compat: ``from src.backend.services.ops.data_quality import DataQualityMonitor`` works.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from src.backend.services.ops.data_quality.apply_mixin import ApplyMixin  # S55 W4: MRO
from src.backend.services.ops.data_quality.check_mixin import CheckMixin  # S55 W4: MRO
from src.backend.services.ops.data_quality.rule_mgmt_mixin import (
    RuleManagementMixin,  # S55 W4: MRO
)
from src.backend.services.ops.data_quality.schema_mixin import (
    SchemaMixin,  # S55 W4: MRO
)

__all__ = (
    "DataQualityMonitor",
    "DQSeverity",
    "DQViolation",
    "DQCheckResult",
    "DQRemediationResult",
    "DQRule",
    "get_dq_monitor",
)


class DataQualityMonitor(RuleManagementMixin, CheckMixin, SchemaMixin, ApplyMixin):
    """Data Quality Monitor (4 mixins = 8 methods + 2 core)."""

    def __init__(self) -> None:
        """Initialize data quality monitor."""
        self._rules: list[DQRule] = []
        self._inferred_schemas: dict[str, dict[str, str]] = {}
        self._stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"checks": 0, "violations": 0}
        )
        self._seen_keys: dict[str, set[str]] = defaultdict(set)
        self._numeric_history: dict[str, list[float]] = defaultdict(list)

    def add_rule(self, rule: DQRule) -> None:
        """Add a data quality rule.

        Args:
            rule: DQRule to add.
        """
        self._rules.append(rule)


# --- Top-level re-exports (S55 W4 decomp: preserve original public surface) ---
class DQSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class DQViolation:
    rule: str
    field: str
    severity: DQSeverity
    message: str
    value: Any = None


@dataclass
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


@dataclass
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


@dataclass
class DQRule:
    """Правило проверки качества данных."""

    name: str
    field: str
    check: str  # "not_null", "type", "range", "unique", "regex"
    params: dict[str, Any] = dataclass_field(default_factory=dict)
    severity: DQSeverity = DQSeverity.WARNING
    enabled: bool = True


_dq_monitor_instance: DataQualityMonitor | None = None


def get_dq_monitor() -> DataQualityMonitor:
    """Возвращает singleton :class:`DataQualityMonitor`.

    Реализация: lazy-init module-level singleton (S150 W3 closes
    S55 W4 stub — pre-existing NotImplementedError).
    """
    global _dq_monitor_instance
    if _dq_monitor_instance is None:
        _dq_monitor_instance = DataQualityMonitor()
    return _dq_monitor_instance
