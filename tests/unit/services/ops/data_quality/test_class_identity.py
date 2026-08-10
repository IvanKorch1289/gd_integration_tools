# ruff: noqa: S101
"""Class-identity verification для data_quality package.

cycle-8/D-AUDIT-803: консолидация 5-way duplication.

Canonical source (``__init__.py``) и 4 mixin files должны резолвить
``DQSeverity / DQViolation / DQCheckResult / DQRule`` к **одному и тому же**
class object (``is`` identity). До фикса каждая поверхность имела свою копию
(``id()`` mismatch → ``A is B == False``).
"""

from __future__ import annotations

from src.backend.services.ops.data_quality import (
    DQCheckResult,
    DQRule,
    DQSeverity,
    DQViolation,
)
from src.backend.services.ops.data_quality.apply_mixin import DQCheckResult as ACR
from src.backend.services.ops.data_quality.apply_mixin import DQRule as AR
from src.backend.services.ops.data_quality.apply_mixin import DQSeverity as AS
from src.backend.services.ops.data_quality.apply_mixin import DQViolation as AV
from src.backend.services.ops.data_quality.check_mixin import DQCheckResult as CCR
from src.backend.services.ops.data_quality.check_mixin import DQRule as CR
from src.backend.services.ops.data_quality.check_mixin import DQSeverity as CS
from src.backend.services.ops.data_quality.check_mixin import DQViolation as CV
from src.backend.services.ops.data_quality.rule_mgmt_mixin import DQCheckResult as RCR
from src.backend.services.ops.data_quality.rule_mgmt_mixin import DQRule as RR
from src.backend.services.ops.data_quality.rule_mgmt_mixin import DQSeverity as RS
from src.backend.services.ops.data_quality.rule_mgmt_mixin import DQViolation as RV
from src.backend.services.ops.data_quality.schema_mixin import DQCheckResult as SCR
from src.backend.services.ops.data_quality.schema_mixin import DQRule as SR
from src.backend.services.ops.data_quality.schema_mixin import DQSeverity as SS
from src.backend.services.ops.data_quality.schema_mixin import DQViolation as SV


def test_dq_severity_identity_consistent() -> None:
    """DQSeverity — single class object across 5 surfaces (cycle-8/D-AUDIT-803)."""
    assert AS is CS is RS is SS is DQSeverity


def test_dq_violation_identity_consistent() -> None:
    """DQViolation — single class object across 5 surfaces (cycle-8/D-AUDIT-803)."""
    assert AV is CV is RV is SV is DQViolation


def test_dq_check_result_identity_consistent() -> None:
    """DQCheckResult — single class object across 5 surfaces (cycle-8/D-AUDIT-803)."""
    assert ACR is CCR is RCR is SCR is DQCheckResult


def test_dq_rule_identity_consistent() -> None:
    """DQRule — single class object across 5 surfaces (cycle-8/D-AUDIT-803)."""
    assert AR is CR is RR is SR is DQRule


def test_dq_violation_instances_are_canonical_type() -> None:
    """DQViolation() через mixin-импорт → isinstance канонического класса.

    До фикса: ``from apply_mixin import DQViolation; DQViolation(...) is not
    isinstance(DQViolation из __init__)``. После фикса — один class object.
    """
    v = AV(rule="r", field="f", severity=DQSeverity.WARNING, message="m")
    assert isinstance(v, DQViolation)


def test_canonical_instance_via_mixin_path_resolves_to_canonical() -> None:
    """Monitor path: rule_mgmt_mixin → DQViolation (injected)."""
    v = RV(rule="r", field="f", severity=RS.WARNING, message="m")
    # v.severity использует DQSeverity из rule_mgmt_mixin.py namespace,
    # но это тот же объект что и канонический.
    assert isinstance(v.severity, DQSeverity)
    assert v.severity is DQSeverity.WARNING
