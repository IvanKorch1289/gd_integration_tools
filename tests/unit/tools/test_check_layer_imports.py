"""Tests для tools/check_layer_imports.py (S58 W2 typer+rich миграция).

Coverage:
* Exit codes 0/1/2 (clean / violations / error);
* Rich table output (через CliRunner, не реально);
* --plain fallback (для CI без rich);
* TOML override;
* --help exit code (typer convention: 0).
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from tools.check_layer_imports import (
    DEFAULT_FORBIDDEN,
    DEFAULT_WHITELIST,
    app,
    scan_directory,
)

runner = CliRunner(mix_stderr=True)


# === Exit codes (via CliRunner) ===


def test_help_exits_zero() -> None:
    """--help → typer convention: exit 0."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "check_layer_imports" in result.stdout


def test_nonexistent_dir_exits_two() -> None:
    """Несуществующая директория → exit 2."""
    result = runner.invoke(app, ["/this/does/not/exist/xyz123"])
    assert result.exit_code == 2
    assert "not found" in result.stdout.lower() or "ERROR" in result.stdout


def test_file_instead_of_dir_exits_two(tmp_path: Path) -> None:
    """Файл вместо директории → exit 2."""
    f = tmp_path / "not_a_dir.py"
    f.write_text("# placeholder\n")
    result = runner.invoke(app, [str(f)])
    assert result.exit_code == 2
    assert "not a directory" in result.stdout.lower() or "ERROR" in result.stdout


def test_clean_dir_exits_zero(tmp_path: Path) -> None:
    """Чистая директория (нет .py с запрещёнными импортами) → exit 0."""
    # Создаём .py файл, который импортирует только core (разрешено)
    (tmp_path / "good.py").write_text("from src.backend.core import foo  # noqa\n")
    result = runner.invoke(app, [str(tmp_path), "--plain"])
    assert result.exit_code == 0
    assert "OK" in result.stdout or "clean" in result.stdout


def test_dir_with_violation_exits_one(tmp_path: Path) -> None:
    """Директория с forbidden import → exit 1."""
    (tmp_path / "bad.py").write_text(
        "from src.backend.infrastructure.repositories import x\n"
    )
    result = runner.invoke(app, [str(tmp_path), "--plain"])
    assert result.exit_code == 1
    assert "ERROR" in result.stdout


# === scan_directory (direct API, для white-box coverage) ===


def test_scan_directory_empty(tmp_path: Path) -> None:
    """Пустая директория → 0 files, 0 violations."""
    files, violations = scan_directory(tmp_path)
    assert files == 0
    assert violations == []


def test_scan_directory_clean_file(tmp_path: Path) -> None:
    """Файл с разрешённым импортом (core) → 0 violations."""
    (tmp_path / "ok.py").write_text("from src.backend.core import x\n")
    files, violations = scan_directory(tmp_path)
    assert files == 1
    assert violations == []


def test_scan_directory_violation(tmp_path: Path) -> None:
    """Файл с forbidden import → 1 violation с правильным (lineno, module, prefix)."""
    (tmp_path / "bad.py").write_text(
        "from src.backend.infrastructure.repositories import x\n"
    )
    files, violations = scan_directory(tmp_path)
    assert files == 1
    assert len(violations) == 1
    py, lineno, module, prefix = violations[0]
    assert lineno == 1
    assert module == "src.backend.infrastructure.repositories"
    assert prefix == "src.backend.infrastructure."


def test_scan_directory_type_checking_skipped(tmp_path: Path) -> None:
    """Imports внутри ``if TYPE_CHECKING:`` НЕ считаются violations."""
    (tmp_path / "typecheck.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from src.backend.infrastructure.foo import x\n"  # noqa
    )
    files, violations = scan_directory(tmp_path)
    assert files == 1
    assert violations == []  # TYPE_CHECKING skip


def test_scan_directory_multiple_violations(tmp_path: Path) -> None:
    """Несколько violations в одном файле → все ловятся."""
    (tmp_path / "multi.py").write_text(
        "from src.backend.infrastructure.a import x\n"
        "from src.backend.infrastructure.b import y\n"
        "from src.backend.services.c import z\n"
    )
    files, violations = scan_directory(tmp_path)
    assert files == 1
    assert len(violations) == 3


def test_scan_directory_syntax_error_no_crash(tmp_path: Path) -> None:
    """SyntaxError в файле → НЕ крашит scan, просто пропускает."""
    (tmp_path / "broken.py").write_text("def x(:\n")  # invalid syntax
    files, violations = scan_directory(tmp_path)
    assert files == 1
    assert violations == []  # SyntaxError → пустой результат для файла


# === TOML parsing (whitelist customization) ===


def test_custom_whitelist_no_violation(tmp_path: Path) -> None:
    """Если ``infrastructure.*`` добавлен в whitelist → НЕ violation."""
    (tmp_path / "ok.py").write_text(
        "from src.backend.infrastructure.foo import x\n"
    )
    files, violations = scan_directory(
        tmp_path,
        forbidden=DEFAULT_FORBIDDEN,
        whitelist=("src.backend.core.", "src.backend.infrastructure."),
    )
    assert files == 1
    assert violations == []


# === Default constants (regression guard) ===


def test_default_forbidden_includes_infrastructure_and_services() -> None:
    """Default forbidden = infrastructure.* + services.* (R3.10d)."""
    assert "src.backend.infrastructure." in DEFAULT_FORBIDDEN
    assert "src.backend.services." in DEFAULT_FORBIDDEN


def test_default_whitelist_includes_core() -> None:
    """Default whitelist = core.* (R3.10d / ADR-001)."""
    assert "src.backend.core." in DEFAULT_WHITELIST
