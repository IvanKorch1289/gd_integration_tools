"""S171 M7 — DirectoryScanProcessor.

Сканирует директорию по glob-паттерну → list файлов.

Pattern (Ponytail, D166): thin wrapper над :mod:`pathlib.Path.glob`
с async I/O через :func:`asyncio.to_thread`.

Differences from FileListProcessor (M6):
- FileList: один glob, синхронный, no filters
- DirectoryScan: recursive (**), min_size filter, mtime filter,
  returns sorted list with metadata
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


class DirectoryScanProcessor(BaseProcessor):
    """Сканирует директорию → list файлов с metadata.

    Args:
        directory: Корневая директория.
        pattern: Glob-паттерн (default ``"*"``). Use ``**`` для recursive.
        min_size: Минимальный размер файла в байтах (optional).
        max_size: Максимальный размер файла в байтах (optional).
        modified_after: Только файлы, изменённые после datetime (optional).
        to: Куда записать список (default ``"body.files"``).
    """

    required_capability: str | None = "rpa.directory.scan"
    audit_event: str | None = "rpa.directory.scan"

    def __init__(
        self,
        *,
        directory: str,
        pattern: str = "*",
        min_size: int | None = None,
        max_size: int | None = None,
        modified_after: datetime | None = None,
        to: str = "body.files",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "directory_scan")
        self.directory = directory
        self.pattern = pattern
        self.min_size = min_size
        self.max_size = max_size
        self.modified_after = modified_after
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        def _scan() -> list[str]:
            root = Path(self.directory)
            if not root.exists():
                return []
            results: list[str] = []
            matches = list(root.glob(self.pattern))
            for path in matches:
                if not path.is_file():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if self.min_size is not None and stat.st_size < self.min_size:
                    continue
                if self.max_size is not None and stat.st_size > self.max_size:
                    continue
                if self.modified_after is not None:
                    mtime = datetime.fromtimestamp(stat.st_mtime)
                    if mtime < self.modified_after:
                        continue
                results.append(str(path))
            return sorted(results)

        files = await asyncio.to_thread(_scan)
        _rpa_logger.info(
            "directory_scan dir=%s pattern=%s count=%d",
            self.directory, self.pattern, len(files),
        )
        self.set_result(exchange, self.target, files)
