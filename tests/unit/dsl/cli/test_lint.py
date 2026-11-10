r"""Tests for ``dsl/cli/lint.py`` — единый capability-aware линтер DSL-YAML.

История модуля (ADR-0434): в проекте было три линтера DSL-YAML
(``tools/dsl_lint.py``, устаревший ``src.backend.dsl.cli.lint`` и
``src.backend.dsl.cli.linter.DSLLinter``). Каноничной стала реализация из
``tools/dsl_lint.py``, перенесённая в ``src.backend.dsl.cli.lint``;
``tools/dsl_lint.py`` — тонкая CLI-обёртка.
"""

from __future__ import annotations

from pathlib import Path

from src.backend.dsl.cli.lint import Finding, lint_file, lint_yaml


def _rules(findings: list[Finding]) -> set[str]:
    """Множество правил, заделенных находками."""
    return {finding.rule for finding in findings}


def test_lint_yaml_invalid_syntax() -> None:
    """Некорректный YAML → finding ``yaml-syntax``."""
    findings = lint_yaml(":\n  invalid: [unclosed")
    assert "yaml-syntax" in _rules(findings)


def test_lint_yaml_root_not_mapping() -> None:
    """YAML-список (не mapping) → ``invalid-root``."""
    findings = lint_yaml("- a\n- b\n")
    assert "invalid-root" in _rules(findings)


def test_lint_yaml_missing_route_id() -> None:
    """Нет ``route_id`` → ``missing-field``."""
    findings = lint_yaml("source: x\nprocessors: []\n")
    assert "missing-field" in _rules(findings)
    assert any("route_id" in finding.message for finding in findings)


def test_lint_yaml_missing_source() -> None:
    """Нет ``source`` → ``missing-field``."""
    findings = lint_yaml("route_id: r\nprocessors: []\n")
    assert "missing-field" in _rules(findings)
    assert any("source" in finding.message for finding in findings)


def test_lint_yaml_processors_not_list() -> None:
    """``processors`` не список → ``invalid-processors``."""
    findings = lint_yaml("route_id: r\nsource: s\nprocessors: nope\n")
    assert "invalid-processors" in _rules(findings)


def test_lint_yaml_valid_has_no_findings() -> None:
    """Корректная спецификация → без находок."""
    findings = lint_yaml(
        "route_id: r\nsource: s\nprocessors:\n  - log:\n      message: hi\n"
    )
    assert findings == []


def test_lint_file_non_yaml_extension_is_skipped(tmp_path: Path) -> None:
    """Не-YAML файл пропускается (без находок)."""
    path = tmp_path / "route.toml"
    path.write_text("route_id = 'r'\n", encoding="utf-8")
    assert lint_file(path) == []


def test_lint_file_missing_returns_empty(tmp_path: Path) -> None:
    """Отсутствующий файл → пустой список (без исключения)."""
    assert lint_file(tmp_path / "nope.yaml") == []
