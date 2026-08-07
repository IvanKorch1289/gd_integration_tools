"""DataQualityMonitor package (S55 W4 decomp from data_quality.py 618 LOC).

10 methods decomposed в 4 mixin files:
- ``rule_mgmt_mixin.py`` (3): add_rules, list_rules, remediate
- ``check_mixin.py`` (2): check, _check_rule
- ``schema_mixin.py`` (2): schema_infer, stats
- ``apply_mixin.py`` (1): _apply_rule (the BIG one, 263 LOC)

Core (__init__ + add_rule) остается в __init__.py.

Backward-compat: ``from src.backend.services.ops.data_quality import DataQualityMonitor`` works.

cycle-8/D-AUDIT-803: DQSeverity / DQViolation / DQCheckResult / DQRule /
DQRemediationResult consolidated в этот ``__init__.py`` (canonical source).
Mixin files (apply/check/rule_mgmt/schema) больше НЕ определяют свои копии —
class identity consistent через post-load injection (см. ниже).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# Module-alias imports — нужны для post-load injection (см. ниже).
# Mixins грузятся ДО dataclasses; они используют class identity через
# globals lookup в method bodies (lazy via ``from __future__ import annotations``).
from src.backend.services.ops.data_quality import apply_mixin as _apply_mixin_module  # cycle-8/D-AUDIT-803
from src.backend.services.ops.data_quality import check_mixin as _check_mixin_module  # cycle-8/D-AUDIT-803
from src.backend.services.ops.data_quality import rule_mgmt_mixin as _rule_mgmt_mixin_module  # cycle-8/D-AUDIT-803
from src.backend.services.ops.data_quality import schema_mixin as _schema_mixin_module  # cycle-8/D-AUDIT-803

# Bare-class imports — для MRO в DataQualityMonitor ниже.
from src.backend.services.ops.data_quality.apply_mixin import ApplyMixin  # S55 W4: MRO
from src.backend.services.ops.data_quality.check_mixin import CheckMixin  # S55 W4: MRO
from src.backend.services.ops.data_quality.rule_mgmt_mixin import RuleManagementMixin  # S55 W4: MRO
from src.backend.services.ops.data_quality.schema_mixin import SchemaMixin  # S55 W4: MRO

__all__ = (
    "DataQualityMonitor",
    "DQSeverity",
    "DQViolation",
    "DQCheckResult",
    "DQRemediationResult",
    "DQRule",
    "get_dq_monitor",
)


# ── Canonical DQ types (cycle-8/D-AUDIT-803) ──────────────────────────
# DO NOT move these out of __init__.py — они single source of truth для
# 5 module surfaces (4 mixin files + this __init__).
class DQSeverity(str, Enum):
    """Severity enum (INFO / WARNING / ERROR / CRITICAL)."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class DQViolation:
    """Single data-quality violation (field, severity, message)."""
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
        """True если нет violations (severity >= ERROR)."""
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


# ── cycle-8/D-AUDIT-803: post-load injection ─────────────────────────
# Mixin files reference DQSeverity/DQViolation/DQCheckResult/DQRule inside
# method bodies (runtime constructor calls). To avoid circular imports
# (each mixin module can't ``from __init__ import`` while __init__ loads them),
# inject canonical class names into each mixin module's namespace AFTER all
# mixin classes are defined. Python looks up unqualified names in the
# function's enclosing module globals at call time, so this makes method
# bodies resolve to the canonical class — guaranteeing ``id()`` consistency
# across all 5 module surfaces.
_apply_mixin_module.DQSeverity = DQSeverity
_apply_mixin_module.DQViolation = DQViolation
_apply_mixin_module.DQCheckResult = DQCheckResult
_apply_mixin_module.DQRule = DQRule
_check_mixin_module.DQSeverity = DQSeverity
_check_mixin_module.DQViolation = DQViolation
_check_mixin_module.DQCheckResult = DQCheckResult
_check_mixin_module.DQRule = DQRule
_rule_mgmt_mixin_module.DQSeverity = DQSeverity
_rule_mgmt_mixin_module.DQViolation = DQViolation
_rule_mgmt_mixin_module.DQCheckResult = DQCheckResult
_rule_mgmt_mixin_module.DQRule = DQRule
_schema_mixin_module.DQSeverity = DQSeverity
_schema_mixin_module.DQViolation = DQViolation
_schema_mixin_module.DQCheckResult = DQCheckResult
_schema_mixin_module.DQRule = DQRule


class DataQualityMonitor(RuleManagementMixin, CheckMixin, SchemaMixin, ApplyMixin):  # cycle-8/D-AUDIT-803
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
