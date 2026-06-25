"""S171 M6 — FileListProcessor (gap fill).

Glob-поиск файлов. async via ``asyncio.to_thread``.
Капабилити: rpa.file.list (read-only, low risk).
"""
from __future__ import annotations

import asyncio

import glob
import os
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


class FileListProcessor(BaseProcessor):
    """Список файлов по glob-паттерну.

    Args:
        pattern: Glob-паттерн (например ``"/tmp/*.txt"``).
        recursive: ``**`` для рекурсивного поиска (default False).
        to: Куда записать список (default ``"body.files"``).
    """

    required_capability: str | None = "rpa.file.list"
    audit_event: str | None = "rpa.file.list"

    def __init__(
        self,
        *,
        pattern: str | None = None,
        recursive: bool = False,
        to: str = "body.files",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "file_list")
        self.pattern = pattern
        self.recursive = recursive
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        pattern = self.pattern or exchange.in_message.body.get("pattern")
        if not pattern:
            raise ValueError("FileListProcessor: pattern обязателен")
        if self.recursive and "**" not in pattern:
            pattern = os.path.join(pattern, "**")

        # Async glob (file I/O в thread pool)
        files = await asyncio.to_thread(glob.glob, pattern, recursive=self.recursive)
        _rpa_logger.info("file_list pattern=%s count=%d", pattern, len(files))
        # Write to body via dotted path (set_result handles it)
        self.set_result(exchange, self.target, sorted(files))
