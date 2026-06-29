"""TDD: FileSearchProcessor (M24 P2 #4, D272).

Поиск подстроки/regex в файлах с фильтром по path glob.
Pattern (D272, Ponytail): thin wrapper.
"""
# ruff: noqa: S101
from __future__ import annotations
import tempfile
from pathlib import Path

import pytest


class TestFileSearchProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.file_search import (
            FileSearchProcessor,
        )
        proc = FileSearchProcessor(path_pattern="**/*.py", pattern="import")
        assert proc.path_pattern == "**/*.py"
        assert proc.pattern == "import"

    def test_search_returns_matches(self) -> None:
        """Поиск в директории — возвращает list matches."""
        from src.backend.dsl.engine.processors.rpa.file_search import (
            FileSearchProcessor,
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "a.py").write_text("import os\nimport sys\n")
            (tmp_path / "b.py").write_text("# no match here\n")
            (tmp_path / "c.txt").write_text("import json\n")  # wrong ext
            proc = FileSearchProcessor(path_pattern="**/*.py", pattern="import")
            matches = proc.search(root=tmp_path)
            assert len(matches) == 2  # a.py + c.txt excluded (txt ext)

    def test_search_with_regex(self) -> None:
        """Regex pattern."""
        from src.backend.dsl.engine.processors.rpa.file_search import (
            FileSearchProcessor,
        )
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "test.py").write_text("foo = 42\nbar = 100\n")
            proc = FileSearchProcessor(path_pattern="**/*.py", pattern=r"\b\w+ = \d+\b")
            matches = proc.search(root=Path(tmp))
            assert len(matches) >= 1
