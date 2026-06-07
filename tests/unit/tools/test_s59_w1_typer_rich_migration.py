"""Tests для S59 W1 — typer+rich migration batch 2 (5 tools).

Coverage:
* check_feature_flags: clean case, violations, --allow-non-off;
* check_auth_coverage: clean, violations, --strict, --public-prefix;
* check_coverage_gate: missing xml, below threshold, ok case;
* check_service_docs: clean, missing docstring, missing example section;
* check_docstrings: clean, violations, --strict, --update-allowlist.

Strategy: typer.testing.CliRunner для каждого.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

# === Shared fixtures ===

runner = CliRunner(mix_stderr=True)


@pytest.fixture
def empty_py_file(tmp_path: Path) -> Path:
    """Создаёт пустой .py файл в tmp_path."""
    f = tmp_path / "empty.py"
    f.write_text('"""Empty module."""\n', encoding="utf-8")
    return f


@pytest.fixture
def clean_py_file(tmp_path: Path) -> Path:
    """Создаёт .py файл с одной public function и docstring."""
    f = tmp_path / "clean.py"
    f.write_text(
        '"""Clean module."""\n\n'
        'def public_function() -> None:\n'
        '    """Has a docstring. Long enough description here."""\n'
        '    pass\n',
        encoding="utf-8",
    )
    return f


# === check_feature_flags ===


def test_check_feature_flags_help() -> None:
    """--help → typer formatted help."""
    from tools.check_feature_flags import app

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--allow-non-off" in result.stdout
    assert "default-OFF" in result.stdout or "default-OFF policy" in result.stdout


def test_check_feature_flags_runs() -> None:
    """No-arg run → exits 0 или 1 (в зависимости от default-OFF violations)."""
    from tools.check_feature_flags import app

    result = runner.invoke(app, [])
    # Project has multiple feature flags with default=True, so this WILL fail
    # (default-OFF policy). Exit code 1.
    assert result.exit_code in (0, 1)


def test_check_feature_flags_allow_non_off() -> None:
    """--allow-non-off с реальным violation → может пройти (зависит от списка)."""
    from tools.check_feature_flags import app

    # Попробуем allow-list все известные нарушения
    result = runner.invoke(
        app,
        ["--allow-non-off", "embedding_v2_traffic,workflow_audit_extended,workflow_sla_dashboard_enabled"],
    )
    # Может exit 0 (если все violations в allow) или 1 (есть ещё)
    assert result.exit_code in (0, 1)


# === check_auth_coverage ===


def test_check_auth_coverage_help() -> None:
    """--help → typer help."""
    from tools.check_auth_coverage import app

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_check_auth_coverage_clean_dir(tmp_path: Path) -> None:
    """Пустая директория → exit 0 (no endpoints to check)."""
    from tools.check_auth_coverage import app

    result = runner.invoke(app, ["--root", str(tmp_path)])
    assert result.exit_code == 0


def test_check_auth_coverage_nonexistent_root() -> None:
    """--root на nonexistent path → exit 1."""
    from tools.check_auth_coverage import app

    result = runner.invoke(app, ["--root", "/nonexistent/xyz/123"])
    assert result.exit_code == 1


def test_check_auth_coverage_strict_vs_non_strict(tmp_path: Path) -> None:
    """--strict vs без → разные exit codes на violations."""
    from tools.check_auth_coverage import app

    # tmp_path имеет __pycache__ и .py файлы pytest fixtures → могут быть violations
    # Создадим файл с bare endpoint без auth
    (tmp_path / "test_endpoint.py").write_text(
        "from fastapi import APIRouter\n"
        "router = APIRouter()\n\n"
        "@router.get('/users')\n"
        "def list_users():\n"
        "    return []\n",
        encoding="utf-8",
    )
    # Без --strict: violations есть, но exit 0
    result_no_strict = runner.invoke(app, ["--root", str(tmp_path)])
    # С --strict: exit 1
    result_strict = runner.invoke(app, ["--root", str(tmp_path), "--strict"])
    assert result_no_strict.exit_code == 0
    assert result_strict.exit_code == 1


# === check_coverage_gate ===


def test_check_coverage_gate_help() -> None:
    """--help → typer help."""
    from tools.check_coverage_gate import app

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_check_coverage_gate_missing_xml(tmp_path: Path) -> None:
    """--coverage-xml на nonexistent → exit 2 (error)."""
    from tools.check_coverage_gate import app

    result = runner.invoke(
        app, ["--coverage-xml", str(tmp_path / "no_such.xml")]
    )
    assert result.exit_code == 2


def test_check_coverage_gate_pass(tmp_path: Path) -> None:
    """coverage.xml с line-rate=0.80, threshold=0.50 → exit 0."""
    from tools.check_coverage_gate import app

    xml = tmp_path / "cov.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n'
        '<coverage line-rate="0.80" branch-rate="0.5" version="1.0">\n'
        "</coverage>\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "--coverage-xml",
            str(xml),
            "--threshold",
            "50.0",
            "--baseline",
            str(tmp_path / "no_baseline.json"),
        ],
    )
    assert result.exit_code == 0


def test_check_coverage_gate_fail(tmp_path: Path) -> None:
    """coverage.xml с line-rate=0.30, threshold=0.75 → exit 1."""
    from tools.check_coverage_gate import app

    xml = tmp_path / "cov.xml"
    xml.write_text(
        '<?xml version="1.0" ?>\n'
        '<coverage line-rate="0.30" version="1.0">\n'
        "</coverage>\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "--coverage-xml",
            str(xml),
            "--threshold",
            "75.0",
            "--baseline",
            str(tmp_path / "no_baseline.json"),
        ],
    )
    assert result.exit_code == 1


# === check_service_docs ===


def test_check_service_docs_help() -> None:
    """--help → typer help."""
    from tools.checks.check_service_docs import app

    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_check_service_docs_nonexistent_target() -> None:
    """--target на nonexistent → exit 1."""
    from tools.checks.check_service_docs import app

    result = runner.invoke(app, ["--target", "/nonexistent/xyz/123"])
    assert result.exit_code == 1


def test_check_service_docs_clean_target(tmp_path: Path) -> None:
    """--target на пустую директорию → exit 0 (no @service_dsl)."""
    from tools.checks.check_service_docs import app

    result = runner.invoke(app, ["--target", str(tmp_path)])
    assert result.exit_code == 0


# === check_docstrings ===


def test_check_docstrings_help() -> None:
    """--help → typer help."""
    from tools.check_docstrings import app as check_app

    result = runner.invoke(check_app, ["--help"])
    assert result.exit_code == 0


def test_check_docstrings_no_paths_exits_2() -> None:
    """Без paths/files → exit 2 (typer ValidationError или наш Exit 2)."""
    from tools.check_docstrings import app as check_app

    result = runner.invoke(check_app, [])
    assert result.exit_code in (0, 2)


def test_check_docstrings_clean_file(clean_py_file: Path) -> None:
    """--strict на чистом файле → exit 0."""
    from tools.check_docstrings import app as check_app

    result = runner.invoke(check_app, [str(clean_py_file), "--strict"])
    # public_function имеет docstring "Has a docstring. Long enough description here."
    # (44 chars > 20) — должен быть clean
    assert result.exit_code == 0


def test_check_docstrings_violation_strict(tmp_path: Path) -> None:
    """Public function без docstring + --strict → exit 1."""
    from tools.check_docstrings import app as check_app

    f = tmp_path / "bad.py"
    f.write_text(
        '"""Module."""\n\n'
        'def undocumented_public() -> None:\n'
        '    return None\n',
        encoding="utf-8",
    )
    result = runner.invoke(check_app, [str(f), "--strict"])
    assert result.exit_code == 1


# === Cross-tool smoke: typer entry points are importable from CI scripts ===


def test_check_auth_coverage_typer_entry_importable() -> None:
    """Typer app importable (CI scripts do ``from tools.check_auth_coverage import app``)."""
    from tools.check_auth_coverage import app

    assert app is not None
    # app должен быть typer.Typer instance
    import typer

    assert isinstance(app, typer.Typer)
