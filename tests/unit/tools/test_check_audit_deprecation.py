"""Tests для tools/check_audit_deprecation.py (S105 W2).

Покрывает:
* ``AuditDeprecationChecker.scan()`` — находит legacy callsites.
* ``_should_exclude()`` — исключает facade, tests, testkit, кэш, venv, сам скрипт.
* ``total_callsites`` / ``total_files`` — счётчики.
* ``report_human()`` / ``report_json()`` — форматы вывода.
* ``main()`` — CLI: default exit 0, --strict exit 1 при callsites.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.check_audit_deprecation import (
    AuditDeprecationChecker,
    main,
)


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_source_tree(tmp_path: Path) -> Path:
    """Создаёт временное дерево с известными legacy callsites.

    Layout:
        tmp_path/
            src/
                core/
                    audit/
                        facade.py     # EXCLUDED
                app/
                    legacy.py        # 2 callsites
                tests/
                        test_app.py  # EXCLUDED
                testkit/
                        helper.py    # EXCLUDED
            tools/
                check_audit_deprecation.py  # EXCLUDED (self)
    """
    src = tmp_path / "src"
    (src / "core/audit").mkdir(parents=True)
    (src / "app").mkdir(parents=True)
    (src / "tests").mkdir(parents=True)
    (src / "testkit").mkdir(parents=True)
    (tmp_path / "tools").mkdir()

    # 1. Facade (должен быть excluded).
    (src / "core/audit/facade.py").write_text(
        "def emit_audit():\n    pass\n"
    )

    # 2. Legacy callsites в production коде.
    (src / "app/legacy.py").write_text(
        "class A:\n"
        "    def _emit_audit(self, x):\n"
        "        return x\n"
        "\n"
        "    def _emit_audit_safe(self, x):\n"
        "        return x\n"
    )

    # 3. Tests (должны быть excluded).
    (src / "tests/test_app.py").write_text(
        "def test_emit():\n"
        "    _emit_audit()  # noqa\n"
    )

    # 4. Testkit (должен быть excluded).
    (src / "testkit/helper.py").write_text(
        "def _emit_audit():\n    pass\n"
    )

    # 5. __pycache__ (должен быть excluded).
    (src / "app/__pycache__").mkdir()
    (src / "app/__pycache__/cached.py").write_text(
        "def _emit_audit():\n    pass\n"
    )

    return tmp_path


# ──────────────────────────────────────────────────────────────────────
# scan + counts
# ──────────────────────────────────────────────────────────────────────


def test_scan_finds_legacy_callsites(temp_source_tree: Path) -> None:
    """scan() находит legacy _emit_audit / _emit_audit_safe callsites."""
    checker = AuditDeprecationChecker(root=temp_source_tree)
    results = checker.scan()

    # Должен найти только legacy.py (2 callsites), остальные excluded.
    assert len(results) == 1
    assert "src/app/legacy.py" in results
    matches = results["src/app/legacy.py"]
    assert len(matches) == 2
    # Проверяем pattern names.
    patterns = {m[2] for m in matches}
    assert "_emit_audit" in patterns
    assert "_emit_audit_safe" in patterns


def test_total_callsites_and_files(temp_source_tree: Path) -> None:
    """total_callsites / total_files — корректные счётчики."""
    checker = AuditDeprecationChecker(root=temp_source_tree)
    checker.scan()

    assert checker.total_callsites == 2
    assert checker.total_files == 1


def test_scan_excludes_facade(temp_source_tree: Path) -> None:
    """Facade.py не появляется в results (canonical location)."""
    checker = AuditDeprecationChecker(root=temp_source_tree)
    results = checker.scan()

    for filename in results.keys():
        assert "facade" not in filename


def test_scan_excludes_tests_and_testkit(temp_source_tree: Path) -> None:
    """Tests/ и testkit/ исключены из сканирования."""
    checker = AuditDeprecationChecker(root=temp_source_tree)
    results = checker.scan()

    for filename in results.keys():
        assert "/tests/" not in filename
        assert "/testkit/" not in filename


def test_scan_excludes_pycache(temp_source_tree: Path) -> None:
    """__pycache__/ исключён из сканирования."""
    checker = AuditDeprecationChecker(root=temp_source_tree)
    results = checker.scan()

    for filename in results.keys():
        assert "__pycache__" not in filename


# ──────────────────────────────────────────────────────────────────────
# Real codebase — sanity check (integration)
# ──────────────────────────────────────────────────────────────────────


def test_real_codebase_finds_legacy_callsites() -> None:
    """На реальном codebase: ≥ 1 callsite (sanity, не точная цифра)."""
    # tests/unit/tools/test_check_audit_deprecation.py → 4 уровня вверх = repo root.
    repo_root = Path(__file__).parent.parent.parent.parent
    checker = AuditDeprecationChecker(root=repo_root)
    checker.scan()

    # Per S105 subagent-2 finding: 77 callsites в 23 файлах.
    # S108 W3 + S109 W1-W4 reduced TD-004: 73 → 29 callsites (-60%).
    # Floor 20 reflects post-S109 baseline (mixin internals — functional completion).
    assert checker.total_callsites >= 20, (
        f"Expected ≥ 20 callsites (post-S109 baseline), got {checker.total_callsites}. "
        f"Files: {sorted(checker._results.keys())[:5]}..."
    )
    assert checker.total_files >= 5


# ──────────────────────────────────────────────────────────────────────
# Reports
# ──────────────────────────────────────────────────────────────────────


def test_report_human_format(temp_source_tree: Path) -> None:
    """report_human() — readable формат с header + counts."""
    checker = AuditDeprecationChecker(root=temp_source_tree)
    checker.scan()

    report = checker.report_human()
    assert "Audit Deprecation Check" in report
    assert "Files scanned" in report
    assert "Total legacy callsites" in report
    assert "src/app/legacy.py: 2" in report


def test_report_json_format(temp_source_tree: Path) -> None:
    """report_json() — валидный JSON с правильной структурой."""
    checker = AuditDeprecationChecker(root=temp_source_tree)
    checker.scan()

    data = json.loads(checker.report_json())
    assert "scanned_files" in data
    assert "files_with_legacy" in data
    assert "total_callsites" in data
    assert "files" in data
    assert "src/app/legacy.py" in data["files"]


# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────


def test_main_default_exit_zero(temp_source_tree: Path) -> None:
    """main() default mode — exit 0 даже с callsites (soft deprecation)."""
    # Прямой вызов main() с sys.argv override.
    old_argv = sys.argv
    try:
        sys.argv = ["check_audit_deprecation", "--root", str(temp_source_tree)]
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0


def test_main_strict_exit_one_with_callsites(temp_source_tree: Path) -> None:
    """main() --strict — exit 1 если есть callsites (CI gate)."""
    old_argv = sys.argv
    try:
        sys.argv = [
            "check_audit_deprecation",
            "--root", str(temp_source_tree),
            "--strict",
        ]
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 1


def test_main_strict_exit_zero_clean_tree(tmp_path: Path) -> None:
    """main() --strict — exit 0 если legacy нет."""
    # Создаём пустое дерево без legacy.
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "app.py").write_text("def clean():\n    pass\n")

    old_argv = sys.argv
    try:
        sys.argv = ["check_audit_deprecation", "--root", str(clean), "--strict"]
        exit_code = main()
    finally:
        sys.argv = old_argv

    assert exit_code == 0


# ──────────────────────────────────────────────────────────────────────
# Subprocess — реальный CLI (sanity)
# ──────────────────────────────────────────────────────────────────────


def test_cli_runs_via_subprocess() -> None:
    """Скрипт запускается через CLI subprocess, exit 0."""
    # tests/unit/tools/test_check_audit_deprecation.py → 4 уровня вверх = repo root.
    repo_root = Path(__file__).parent.parent.parent.parent
    script = repo_root / "tools/check_audit_deprecation.py"

    result = subprocess.run(
        [str(repo_root / ".venv/bin/python"), str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(repo_root),
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "Audit Deprecation Check" in result.stdout
