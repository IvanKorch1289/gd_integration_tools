"""Unit-тесты для blueprint loader (Wave [wave:s5/k3-w6-blueprints])."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.dsl.blueprint_loader import (
    DEFAULT_BLUEPRINTS_DIR,
    discover_blueprints,
    load_blueprint,
)


def test_discover_blueprints_finds_all_yamls() -> None:
    specs = discover_blueprints()
    names = {s.name for s in specs}
    assert "api_normalize" in names
    assert "cdc_enrich" in names
    assert "ai_pipeline" in names
    assert "saga_with_compensation" in names


def test_load_cdc_enrich_blueprint() -> None:
    path = DEFAULT_BLUEPRINTS_DIR / "cdc_enrich.yaml"
    spec = load_blueprint(path)
    assert spec.name == "cdc_enrich"
    assert spec.version == "1.0.0"
    assert "cdc" in spec.tags
    assert spec.required_param_names()
    assert any(p.name == "cdc_table" for p in spec.params)


def test_load_ai_pipeline_blueprint() -> None:
    path = DEFAULT_BLUEPRINTS_DIR / "ai_pipeline.yaml"
    spec = load_blueprint(path)
    assert spec.name == "ai_pipeline"
    assert spec.steps  # должны быть шаги
    assert any("llm_call" in str(step) for step in spec.steps)


def test_load_saga_with_compensation_blueprint() -> None:
    path = DEFAULT_BLUEPRINTS_DIR / "saga_with_compensation.yaml"
    spec = load_blueprint(path)
    assert spec.name == "saga_with_compensation"
    assert any("saga" in str(s) for s in spec.steps)
    # 6 параметров на 3 шага: action+compensate
    param_names = {p.name for p in spec.params}
    assert "step_1_action" in param_names
    assert "step_3_compensate" in param_names


def test_load_invalid_blueprint(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: a_valid_blueprint", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required 'blueprint' field"):
        load_blueprint(bad)


def test_smoke_compilation_each_blueprint_steps_non_empty() -> None:
    specs = discover_blueprints()
    for spec in specs:
        assert spec.steps, f"Blueprint {spec.name} must have non-empty steps"
        assert spec.source, f"Blueprint {spec.name} must have 'from'"
