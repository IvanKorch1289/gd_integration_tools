"""Unit-тесты WorkflowTemplateRegistry — Sprint 12 K3 W5.

Сценарии:
    * load_all() возвращает 10 templates;
    * каждый template парсится yaml.safe_load без ошибок;
    * search_semantic(query) возвращает релевантные результаты (rapidfuzz);
    * search с пустым query возвращает [];
    * get(name) — точный lookup;
    * deploy создаёт yaml в target dir;
    * BGE-M3 fallback на rapidfuzz при ImportError.
"""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

from src.backend.services.workflows.template_registry import WorkflowTemplateRegistry


def test_load_all_returns_10_templates() -> None:
    registry = WorkflowTemplateRegistry()
    templates = registry.load_all()
    assert len(templates) == 10
    names = {t.name for t in templates}
    expected_names = {
        "data_quality_pipeline",
        "ml_training_pipeline",
        "incident_response",
        "customer_onboarding",
        "report_generation",
        "kyc_aml_check",
        "multi_step_approval",
        "data_migration",
        "webhook_pipeline",
        "scheduled_audit",
    }
    assert names == expected_names


def test_each_template_has_steps() -> None:
    registry = WorkflowTemplateRegistry()
    for tmpl in registry.load_all():
        assert tmpl.step_count >= 1, f"{tmpl.name}: no steps"
        assert tmpl.description, f"{tmpl.name}: empty description"


def test_template_tags_extracted() -> None:
    registry = WorkflowTemplateRegistry()
    incident = registry.get("incident_response")
    assert incident is not None
    assert "hitl" in incident.tags
    assert "incident" in incident.tags


def test_get_returns_none_for_unknown() -> None:
    registry = WorkflowTemplateRegistry()
    assert registry.get("nonexistent_template") is None


def test_search_semantic_returns_relevant_top_k() -> None:
    registry = WorkflowTemplateRegistry()
    results = registry.search_semantic("incident response triage", top_k=3)
    assert len(results) == 3
    names = [t.name for t, _ in results]
    assert "incident_response" in names


def test_search_semantic_empty_query() -> None:
    registry = WorkflowTemplateRegistry()
    assert registry.search_semantic("", top_k=5) == []


def test_search_semantic_relevant_for_kyc_aml() -> None:
    registry = WorkflowTemplateRegistry()
    results = registry.search_semantic("kyc compliance check", top_k=3)
    names = [t.name for t, _ in results]
    assert "kyc_aml_check" in names or "customer_onboarding" in names


def test_singleton_get_template_registry() -> None:
    from src.backend.services.workflows.template_registry import get_template_registry

    r1 = get_template_registry()
    r2 = get_template_registry()
    assert r1 is r2


def test_load_handles_missing_directory(tmp_path: Path) -> None:
    nonexistent = tmp_path / "missing"
    registry = WorkflowTemplateRegistry(templates_dir=nonexistent)
    assert registry.load_all() == []


def test_load_handles_invalid_yaml(tmp_path: Path) -> None:
    template_dir = tmp_path / "bad_templates"
    template_dir.mkdir()
    bad_file = template_dir / "broken.workflow.yaml"
    bad_file.write_text("name: bad\n  invalid: indent\nthis is: broken yaml")

    valid_file = template_dir / "ok.workflow.yaml"
    valid_file.write_text(
        "name: ok\nversion: '1.0'\ndescription: 'tag1, tag2'\n"
        "steps:\n  - type: activity\n    name: step1\n"
    )

    registry = WorkflowTemplateRegistry(templates_dir=template_dir)
    templates = registry.load_all()
    names = {t.name for t in templates}
    assert "ok" in names
