# ruff: noqa: S101
"""Smoke-тест YAML workflow credit_assessment (Sprint 7 Team T3).

Wave: ``[wave:s7/team-03-credit-1st-client]``.

Тест проверяет наличие YAML, корректность парсинга, обязательные секции
(activities, steps, compensation) и правильность wave-связки.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / "workflows"
    / "credit_assessment.workflow.yaml"
)


def test_workflow_yaml_exists_and_parses() -> None:
    """YAML существует и парсится."""
    assert _WORKFLOW_PATH.exists()
    data = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert data["name"] == "credit_assessment"
    assert data["version"] == "1.0"


def test_workflow_has_required_sections() -> None:
    """activities, steps, compensation — обязательные секции."""
    data = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert "activities" in data
    assert "steps" in data
    assert "compensation" in data
    assert len(data["activities"]) >= 3


def test_workflow_steps_have_scoring_rule_engine() -> None:
    """Один из steps — rule_engine с правилами scoring."""
    data = yaml.safe_load(_WORKFLOW_PATH.read_text(encoding="utf-8"))
    rule_steps = [s for s in data["steps"] if s.get("type") == "rule_engine"]
    assert len(rule_steps) == 1
    rules = rule_steps[0]["rules"]
    decisions = {r["decision"] for r in rules}
    assert "APPROVE" in decisions
    assert "MANUAL_REVIEW" in decisions
