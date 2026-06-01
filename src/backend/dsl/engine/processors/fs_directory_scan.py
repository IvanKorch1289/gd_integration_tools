"""Directory Scan processor — lists files matching a glob pattern in a directory.

Scans a directory (optionally recursive) for files matching a glob pattern,
sorts them, and sets the result as an exchange property.

S35 GAP-INT-3: batch file processing for ETL/ingestion pipelines.
"""

from __future__ import annotations

import glob
import os
from typing import Any

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("DirectoryScanProcessor",)


class DirectoryScanProcessor(BaseProcessor):
    """Scans a directory for files matching a glob pattern.

    Scans ``path`` for files matching ``pattern`` (e.g. ``*.csv``,
    ``**/*.json``).  Results are sorted by ``sort_by`` (``name``,
    ``mtime`` or ``size``) and written to
    ``exchange.properties[result_property]`` as a list of dicts with keys
    ``path``, ``name``, ``size``, ``mtime``.

    Used in batch-processing routes to enumerate input files before
    feeding them to a downstream pipeline (e.g. via ForEachProcessor).
    """

    side_effect = SideEffectKind.SIDE_EFFECTING
    compensatable = True

    def __init__(
        self,
        path: str,
        pattern: str = "*",
        *,
        recursive: bool = False,
        max_files: int = 1000,
        sort_by: str = "name",
        result_property: str = "directory_scan_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"dir_scan:{path}:{pattern}")
        self._path = path
        self._pattern = pattern
        self._recursive = recursive
        self._max_files = max_files
        self._sort_by = sort_by
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        # Resolve path — allow dynamic path via property or body
        path = self._path
        if not path:
            body = exchange.in_message.body
            path = body.get("path") if isinstance(body, dict) else str(body)

        if not path:
            exchange.fail("DirectoryScanProcessor: no path provided")
            return

        # Guard against path traversal
        try:
            resolved = os.path.realpath(path)
            if not os.path.isdir(resolved):
                exchange.fail(f"DirectoryScanProcessor: not a directory: {path}")
                return
        except OSError as exc:
            exchange.fail(f"DirectoryScanProcessor: path error: {exc}")
            return

        # Glob pattern — prepend recursive marker if needed
        glob_pattern = self._pattern
        if self._recursive and not glob_pattern.startswith("**"):
            # Convert simple "*.csv" → "**/*.csv" for recursive walk
            if glob_pattern.startswith("*"):
                glob_pattern = "**/" + glob_pattern
            else:
                glob_pattern = "**/" + glob_pattern

        search_root = resolved if not self._recursive else resolved
        try:
            if self._recursive:
                matched = glob.glob(
                    os.path.join(glob_pattern),
                    root_dir=search_root,
                    recursive=True,
                )
            else:
                matched = glob.glob(
                    os.path.join(search_root, glob_pattern),
                    recursive=False,
                )
        except OSError as exc:
            exchange.fail(f"DirectoryScanProcessor: glob error: {exc}")
            return

        # Build result entries with metadata
        entries: list[dict[str, Any]] = []
        for rel_path in matched[: self._max_files]:
            full = os.path.join(search_root, rel_path) if self._recursive else os.path.join(search_root, rel_path)
            try:
                stat = os.stat(full)
                entries.append(
                    {
                        "path": full,
                        "name": os.path.basename(rel_path) if self._recursive else os.path.basename(full),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
            except OSError:
                # Skip files that disappear between glob and stat
                continue

        # Sort
        if self._sort_by == "mtime":
            entries.sort(key=lambda e: e["mtime"])
        elif self._sort_by == "size":
            entries.sort(key=lambda e: e["size"])
        else:
            entries.sort(key=lambda e: e["name"])

        exchange.set_property(self._result_property, entries)

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "directory_scan": {
                "path": self._path,
                "pattern": self._pattern,
                "recursive": self._recursive,
                "max_files": self._max_files,
                "sort_by": self._sort_by,
                "result_property": self._result_property,
            }
        }
