"""Tests for core/utils/doc_path_validator.py (S98 — coverage push).

Covers: DocPathValidator + validate_doc_paths entrypoint.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_validate_doc_paths_with_explicit_root(tmp_path: Path) -> None:
    """validate_doc_paths(explicit_repo_root) returns dict с categories."""
    from src.backend.core.utils.doc_path_validator import validate_doc_paths

    # Create minimal repo structure.
    (tmp_path / "src/backend").mkdir(parents=True)
    (tmp_path / "extensions").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "test.md").write_text("Real file: `src/backend/real.py`")

    result = validate_doc_paths(tmp_path)
    # Returns {category: [missing_paths]} — only populated if there are missing refs.
    assert isinstance(result, dict)
    # real.py doesn't exist → must be in missing list.
    assert "src_backend" in result
    assert "real.py" in result["src_backend"]


def test_doc_path_validator_collect_referenced(tmp_path: Path) -> None:
    """DocPathValidator.collect_referenced_paths finds src/backend и extensions refs."""
    from src.backend.core.utils.doc_path_validator import DocPathValidator

    (tmp_path / "src/backend").mkdir(parents=True)
    (tmp_path / "extensions").mkdir()
    (tmp_path / "docs").mkdir()

    doc = tmp_path / "docs" / "x.md"
    doc.write_text(
        "Use `src/backend/foo/bar.py` and `extensions/baz.py` in production."
    )

    validator = DocPathValidator(tmp_path)
    refs = validator.collect_referenced_paths()
    assert "foo/bar.py" in refs["src_backend"]
    assert "baz.py" in refs["extensions"]


def test_doc_path_validator_skips_build_dir(tmp_path: Path) -> None:
    """DocPathValidator skips _build directory."""
    from src.backend.core.utils.doc_path_validator import DocPathValidator

    (tmp_path / "src/backend").mkdir(parents=True)
    (tmp_path / "extensions").mkdir()
    (tmp_path / "docs/_build").mkdir(parents=True)

    prod_doc = tmp_path / "docs" / "good.md"
    prod_doc.write_text("`src/backend/real.py`")
    build_doc = tmp_path / "docs/_build" / "gen.md"
    build_doc.write_text("`src/backend/phantom.py`")

    validator = DocPathValidator(tmp_path)
    refs = validator.collect_referenced_paths()
    assert "real.py" in refs["src_backend"]
    assert "phantom.py" not in refs["src_backend"]


def test_doc_path_validator_find_missing(tmp_path: Path) -> None:
    """find_missing: returns dict with missing paths per category."""
    from src.backend.core.utils.doc_path_validator import DocPathValidator

    (tmp_path / "src/backend").mkdir(parents=True)
    (tmp_path / "extensions").mkdir()
    (tmp_path / "docs").mkdir()

    doc = tmp_path / "docs" / "x.md"
    doc.write_text(
        "`src/backend/ghost.py` and `extensions/phantom.py`"
    )

    validator = DocPathValidator(tmp_path)
    missing = validator.find_missing()
    assert "ghost.py" in missing.get("src_backend", [])
    assert "phantom.py" in missing.get("extensions", [])


def test_doc_path_validator_no_missing(tmp_path: Path) -> None:
    """find_missing: returns empty dict when all paths exist."""
    from src.backend.core.utils.doc_path_validator import DocPathValidator

    (tmp_path / "src/backend/real.py").parent.mkdir(parents=True)
    (tmp_path / "src/backend/real.py").write_text("# ok")
    (tmp_path / "extensions/real.py").parent.mkdir(parents=True)
    (tmp_path / "extensions/real.py").write_text("# ok")
    (tmp_path / "docs").mkdir()

    doc = tmp_path / "docs" / "x.md"
    doc.write_text("`src/backend/real.py` and `extensions/real.py`")

    validator = DocPathValidator(tmp_path)
    missing = validator.find_missing()
    assert missing == {}


def test_validate_doc_paths_uses_cwd_or_env(tmp_path: Path, monkeypatch) -> None:
    """validate_doc_paths без explicit root: использует REPO_ROOT env."""
    from src.backend.core.utils.doc_path_validator import validate_doc_paths

    monkeypatch.setenv("REPO_ROOT", str(tmp_path))
    (tmp_path / "src/backend").mkdir(parents=True)
    (tmp_path / "extensions").mkdir()
    (tmp_path / "docs").mkdir()

    # Should not raise even with no real refs.
    result = validate_doc_paths()
    assert isinstance(result, dict)


def test_doc_path_validator_module_dunder_all() -> None:
    """__all__ = ('DocPathValidator', 'validate_doc_paths')."""
    import src.backend.core.utils.doc_path_validator as mod

    assert mod.__all__ == ("DocPathValidator", "validate_doc_paths")
