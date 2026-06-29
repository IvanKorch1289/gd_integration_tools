"""FileSearchProcessor (M24 P2 #4, D272).

Поиск подстроки/regex в файлах с фильтром по path glob.
Pattern (D272, Ponytail): thin wrapper, no abstractions.
"""
# ruff: noqa: E501
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("dsl.rpa.file_search")

__all__ = ("FileSearchProcessor",)


class FileSearchProcessor:
    """Поиск подстроки/regex в файлах.

    Args:
        path_pattern: glob pattern (например, "**/*.py").
        pattern: regex pattern.
        max_results: hard cap (Ponytail YAGNI).
    """

    def __init__(
        self,
        *,
        path_pattern: str = "**/*",
        pattern: str = "",
        max_results: int = 1000,
    ) -> None:
        self.path_pattern = path_pattern
        self.pattern = pattern
        self.max_results = max_results

    def search(self, root: Path) -> list[dict[str, Any]]:
        """Поиск в директории. Returns [{file, line_no, line, match}, ...]."""
        if not self.pattern:
            return []
        try:
            regex = re.compile(self.pattern)
        except re.error as exc:
            _logger.warning("file_search.bad_pattern pattern=%s: %s", self.pattern, exc)
            return []
        results: list[dict[str, Any]] = []
        for path in root.glob(self.path_pattern):
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line_no, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    results.append({
                        "file": str(path.relative_to(root)),
                        "line_no": line_no,
                        "line": line,
                        "match": regex.search(line).group(0),
                    })
                    if len(results) >= self.max_results:
                        _logger.info("file_search.truncated max=%d", self.max_results)
                        return results
        return results
