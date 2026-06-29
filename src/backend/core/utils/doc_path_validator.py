"""DocPathValidator (S171 M26-P0-2, D288).

Validates paths cited in docs/ against actual files in src/backend/ and extensions/.
Ponytail YAGNI: AST-based regex, no sphinx dependency.
"""
# ruff: noqa: E501
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("core.utils.doc_path_validator")

__all__ = ("DocPathValidator", "validate_doc_paths")


class DocPathValidator:
    """Validates path references в docs/.

    Usage::

        result = validate_doc_paths(repo_root)
        if result["missing"]:
            logger.warning("Missing: %s", result["missing"])
    """

    SRC_BACKEND_PATTERN = re.compile(r"`src/backend/([a-zA-Z_/\.]+\.py)`")
    EXTENSIONS_PATTERN = re.compile(r"`extensions/([a-zA-Z_/\.]+\.py)`")

    def __init__(self, repo_root: Path) -> None:
        self._repo_root = repo_root
        self._src_backend = repo_root / "src/backend"
        self._extensions = repo_root / "extensions"
        self._docs_root = repo_root / "docs"

    def collect_referenced_paths(self) -> dict[str, set[str]]:
        """Collect all referenced paths from source docs (excluding _build)."""
        referenced: dict[str, set[str]] = {"src_backend": set(), "extensions": set()}
        for doc_file in self._docs_root.rglob("*.md"):
            if "_build" in doc_file.parts:
                continue
            content = doc_file.read_text(encoding="utf-8", errors="ignore")
            for m in self.SRC_BACKEND_PATTERN.finditer(content):
                referenced["src_backend"].add(m.group(1))
            for m in self.EXTENSIONS_PATTERN.finditer(content):
                referenced["extensions"].add(m.group(1))
        return referenced

    def find_missing(self) -> dict[str, list[str]]:
        """Return dict of missing paths per category."""
        referenced = self.collect_referenced_paths()
        missing: dict[str, list[str]] = {}
        for ref in sorted(referenced["src_backend"]):
            if not (self._src_backend / ref).exists():
                missing.setdefault("src_backend", []).append(ref)
        for ref in sorted(referenced["extensions"]):
            if not (self._extensions / ref).exists():
                missing.setdefault("extensions", []).append(ref)
        return missing


def validate_doc_paths(repo_root: Path | None = None) -> dict[str, Any]:
    """Validate all doc references in docs/."""
    if repo_root is None:
        repo_root = Path("/home/user/dev/gd_integration_tools")
    validator = DocPathValidator(repo_root)
    return validator.find_missing()
