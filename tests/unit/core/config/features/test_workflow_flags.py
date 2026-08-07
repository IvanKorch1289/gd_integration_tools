"""Unit tests for cycle-3/D-AUDIT-07 — WorkflowFlags defaults lie fix.

Проверяет, что 4 флага (workflow_legacy_disabled, workflow_yaml_round_trip,
workflow_bpmn_import, workflow_gateways_enabled) имеют ``default=False`` —
что соответствует ``description="default-OFF ..."`` (а не default=True как
было до фикса). PHASE-3-PLAN.md §2 T-07 / C3-07.
"""

from __future__ import annotations

from src.backend.core.config.features.workflow import WorkflowFlags


def test_workflow_legacy_disabled_default_false() -> None:
    """workflow_legacy_disabled: default=False (не default=True)."""
    assert WorkflowFlags().workflow_legacy_disabled is False


def test_workflow_yaml_round_trip_default_false() -> None:
    """workflow_yaml_round_trip: default=False (не default=True)."""
    assert WorkflowFlags().workflow_yaml_round_trip is False


def test_workflow_bpmn_import_default_false() -> None:
    """workflow_bpmn_import: default=False (не default=True)."""
    assert WorkflowFlags().workflow_bpmn_import is False


def test_workflow_gateways_enabled_default_false() -> None:
    """workflow_gateways_enabled: default=False (не default=True)."""
    assert WorkflowFlags().workflow_gateways_enabled is False
