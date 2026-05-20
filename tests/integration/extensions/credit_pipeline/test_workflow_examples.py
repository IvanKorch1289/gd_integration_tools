"""Integration tests AI workflow examples — Sprint 12 K4 W1.

Каждый из 3 example yaml парсится через ``yaml.safe_load`` без ошибок
и проходит базовую smoke-валидацию структуры (поля name/version/steps).

Полная валидация через :class:`WorkflowDeclaration.model_validate`
требует feature-flag ``workflow_yaml_round_trip=True``.
"""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest
import yaml as _yaml

_EXTENSIONS_DIR = (
    Path(__file__).resolve().parents[3].parent
    / "extensions"
    / "credit_pipeline"
    / "workflows"
)


def _yaml_files() -> list[Path]:
    return sorted(_EXTENSIONS_DIR.glob("*.workflow.yaml"))


@pytest.mark.parametrize("yaml_path", _yaml_files(), ids=lambda p: p.stem)
def test_yaml_parses(yaml_path: Path) -> None:
    """Каждый workflow.yaml должен парситься без ошибок."""
    data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "name" in data
    assert "version" in data
    assert "steps" in data
    assert len(data["steps"]) >= 1


def test_three_examples_present() -> None:
    """Sprint 12 K4 W1 DoD — 3 example yaml файла."""
    yamls = _yaml_files()
    names = {p.name.removesuffix(".workflow.yaml") for p in yamls}
    expected = {
        "credit_assessment",
        "rag_augmented_saga",
        "multi_agent_supervisor",
        "code_interpreter_loop",
    }
    assert expected.issubset(names), (
        f"Ожидаются S12 example yaml; найдены: {names}"
    )


def test_readme_exists() -> None:
    readme = _EXTENSIONS_DIR / "README.md"
    assert readme.exists()
    content = readme.read_text(encoding="utf-8")
    assert "Sprint 12 K4 W1" in content
