"""ADR-0433 — линтер workflow-спецификаций (``*.workflow.yaml``)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_TOOL = Path("tools/check_workflow_specs.py")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    """Запустить линтер в текущем репозитории."""
    return subprocess.run(
        [sys.executable, str(_TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_linter_passes_on_current_tree() -> None:
    """Все workflow-спецификации проекта валидны."""
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Workflow-спецификации: OK" in result.stdout


def test_linter_detects_unknown_activity(tmp_path: Path) -> None:
    """Неизвестное имя activity → находка с путём файла."""
    from tools import check_workflow_specs as linter

    spec = tmp_path / "broken.workflow.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "name": "broken",
                "version": "1.0",
                "steps": [{"type": "activity", "name": "no.such.activity"}],
            }
        ),
        encoding="utf-8",
    )

    findings = linter.check_spec(spec)
    assert findings, "неизвестная activity не обнаружена"
    assert "no.such.activity" in findings[0]


def test_linter_detects_invalid_step_field(tmp_path: Path) -> None:
    """Невалидное поле шага → находка с указанием шага."""
    from tools import check_workflow_specs as linter

    spec = tmp_path / "bad_field.workflow.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "name": "bad_field",
                "version": "1.0",
                "steps": [{"type": "activity", "name": "ai.run_agent", "timeout_s": "soon"}],
            }
        ),
        encoding="utf-8",
    )

    findings = linter.check_spec(spec)
    assert findings, "невалидное поле шага не обнаружено"
    assert str(spec) in findings[0], findings[0]


def test_compiler_activities_are_registered() -> None:
    """Activity, генерируемые компилятором, зарегистрированы в мосте."""
    from tools import check_workflow_specs as linter

    assert linter.check_compiler_activities() == []
