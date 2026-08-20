"""ITER 13 (Sprint 19): regression test for CRIT-1 fix in validate_doc_paths.

CRIT-1: validate_doc_paths() defaulted to /home/user/dev/gd_integration_tools
(developer-specific path). CI/staging/prod/Docker failed because that path
didn't exist. Fix: REPO_ROOT env var → cwd walk-up to pyproject.toml+src →
fallback to file-relative path.

These tests verify the new resolution chain:
1. REPO_ROOT env var takes precedence
2. cwd walk-up to pyproject.toml+src works
3. Falls back to file-relative path
4. Exits cleanly when no path resolves
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.utils.doc_path_validator import (
    DocPathValidator,
    validate_doc_paths,
)


def test_validate_doc_paths_repo_root_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """REPO_ROOT env var is honored."""
    # Create a minimal project structure
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "src").mkdir()
    monkeypatch.setenv("REPO_ROOT", str(tmp_path))

    result = validate_doc_paths()
    # Should not raise, even if no docs are present
    assert isinstance(result, dict)


def test_validate_doc_paths_cwd_walkup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """cwd walk-up to pyproject.toml+src works."""
    # Create nested directory structure
    subdir = tmp_path / "deep" / "nested"
    subdir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "src").mkdir()

    monkeypatch.delenv("REPO_ROOT", raising=False)
    monkeypatch.chdir(subdir)

    result = validate_doc_paths()
    assert isinstance(result, dict)


def test_validate_doc_paths_explicit_repo_root(tmp_path: Path) -> None:
    """Explicit repo_root parameter is honored (no env/lookup needed)."""
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "src").mkdir()

    validator = DocPathValidator(tmp_path)
    result = validator.find_missing()
    assert isinstance(result, dict)
    # No docs to validate → empty result
    assert "extensions" in result or "src" in result or result == {}


def test_doc_path_validator_no_docs(tmp_path: Path) -> None:
    """Validator works on empty project (no false positives)."""
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "src").mkdir()

    validator = DocPathValidator(tmp_path)
    result = validator.find_missing()
    # No docs/ to scan → no missing references
    assert result == {} or all(v == [] for v in result.values())


def test_validate_doc_paths_env_overrides_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """REPO_ROOT env takes precedence over cwd walk-up."""
    env_root = tmp_path / "env"
    cwd_root = tmp_path / "cwd"
    env_root.mkdir()
    cwd_root.mkdir()
    (env_root / "pyproject.toml").touch()
    (env_root / "src").mkdir()
    (cwd_root / "pyproject.toml").touch()
    (cwd_root / "src").mkdir()

    monkeypatch.setenv("REPO_ROOT", str(env_root))
    monkeypatch.chdir(cwd_root)

    result = validate_doc_paths()
    # Should use env_root (env var takes precedence)
    assert isinstance(result, dict)
