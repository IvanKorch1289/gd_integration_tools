"""Tests for path safety utility (processors/_path_safety.py).

Wave: [tech-debt/coverage].
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.backend.dsl.engine.processors._path_safety import (
    PathTraversalError,
    validate_path,
)


class TestValidatePath:
    """Tests for validate_path function."""

    def test_empty_path_raises(self) -> None:
        with pytest.raises(PathTraversalError, match="non-empty string"):
            validate_path("")

    def test_non_string_raises(self) -> None:
        with pytest.raises(PathTraversalError, match="non-empty string"):
            validate_path(None)  # type: ignore[arg-type]

    def test_traversal_detected(self) -> None:
        with pytest.raises(PathTraversalError, match="traversal"):
            validate_path("../../../etc/passwd")

    def test_traversal_in_filename(self) -> None:
        # ".." only in path.split("/") triggers detection
        with pytest.raises(PathTraversalError, match="traversal"):
            validate_path("foo/../bar")

    def test_valid_relative_path(self) -> None:
        # Use a path under one of the default allowed prefixes
        result = validate_path("/data/uploads/file.txt")
        assert result.endswith("uploads/file.txt")

    def test_valid_export_path(self) -> None:
        result = validate_path("/data/exports/report.csv")
        assert result.endswith("exports/report.csv")

    def test_path_outside_allowed_raises(self) -> None:
        with pytest.raises(PathTraversalError, match="outside allowed"):
            validate_path("/etc/passwd")

    def test_custom_allowed_prefix_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", "/custom/path")
        result = validate_path("/custom/path/file.txt")
        assert result.endswith("custom/path/file.txt")

    def test_custom_prefix_blocks_others(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", "/custom/path")
        with pytest.raises(PathTraversalError, match="outside allowed"):
            validate_path("/data/uploads/file.txt")

    def test_multiple_custom_prefixes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", "/a:/b")
        assert validate_path("/a/file.txt").endswith("/a/file.txt")
        assert validate_path("/b/file.txt").endswith("/b/file.txt")

    def test_resolves_symlinks(self) -> None:
        # Path.resolve() is called; we just verify it doesn't crash
        result = validate_path("/data/uploads/./file.txt")
        assert "./" not in result


class TestPathTraversalError:
    """Tests for PathTraversalError exception."""

    def test_is_value_error_subclass(self) -> None:
        assert issubclass(PathTraversalError, ValueError)

    def test_can_be_caught_as_value_error(self) -> None:
        with pytest.raises(ValueError):
            raise PathTraversalError("test")
