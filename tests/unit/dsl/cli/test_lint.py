r"""Tests for dsl/cli/lint.py (cycle 227 — coverage push).

Per CYCLE-220 analysis, coverage target 77% → 80% (analyst item #12).
`lint.py` (71 LOC) is a small module without tests — add regression
tests for public API (`lint_file`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.dsl.cli.lint import lint_file


def test_lint_file_missing(tmp_path: Path) -> None:
    """Non-existent file → list с error."""
    errors = lint_file(tmp_path / "nope.yaml")
    assert len(errors) == 1
    assert "File not found" in errors[0]


def test_lint_file_invalid_yaml(tmp_path: Path) -> None:
    """Invalid YAML → list с error."""
    p = tmp_path / "bad.yaml"
    p.write_text(":\n  invalid: [unclosed", encoding="utf-8")
    errors = lint_file(p)
    assert any("Invalid YAML" in e for e in errors)


def test_lint_file_root_not_mapping(tmp_path: Path) -> None:
    """YAML list (not mapping) → error."""
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    errors = lint_file(p)
    assert "Root must be a mapping" in errors


def test_lint_file_missing_route_id(tmp_path: Path) -> None:
    """Valid YAML but no route_id → error."""
    p = tmp_path / "no_route.yaml"
    p.write_text("source: x\n", encoding="utf-8")
    errors = lint_file(p)
    assert any("route_id" in e for e in errors)


def test_lint_file_invalid_processor_spec(tmp_path: Path) -> None:
    """Processor spec с 2 keys → error."""
    p = tmp_path / "bad_proc.yaml"
    p.write_text(
        "route_id: x\nprocessors:\n  - foo: bar\n    baz: qux\n", encoding="utf-8"
    )
    errors = lint_file(p)
    assert any("invalid spec" in e for e in errors)


def test_lint_file_valid(tmp_path: Path) -> None:
    """Valid YAML → empty list (lint passed)."""
    p = tmp_path / "good.yaml"
    p.write_text(
        "route_id: my_route\nsource: my_source\nprocessors:\n  - processor_a\n  - proc_b:\n      config: value\n",
        encoding="utf-8",
    )
    errors = lint_file(p)
    assert errors == []


def test_lint_file_string_processor(tmp_path: Path) -> None:
    """Processor as string (shorthand) → no error."""
    p = tmp_path / "string_proc.yaml"
    p.write_text(
        "route_id: x\nsource: y\nprocessors:\n  - just_a_string\n",
        encoding="utf-8",
    )
    errors = lint_file(p)
    assert errors == []
