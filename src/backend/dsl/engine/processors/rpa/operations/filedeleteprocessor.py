"""S171 M6 — FileDeleteProcessor (gap fill).

Безопасное удаление файла/директории.
Капабилити: rpa.file.delete (RCE-shaped).
"""
from __future__ import annotations

import asyncio

import os
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


class FileDeleteProcessor(BaseProcessor):
    """Удаляет файл или директорию (recursive).

    Args:
        path: Путь к файлу/директории.
        missing_ok: Не raise если path не существует (default True).
        to: Куда записать результат (default ``"body"``).
    """

    required_capability: str | None = "rpa.file.delete"
    audit_event: str | None = "rpa.file.delete"

    def __init__(
        self,
        *,
        path: str | None = None,
        missing_ok: bool = True,
        to: str = "body",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "file_delete")
        self.path = path
        self.missing_ok = missing_ok
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        path = self.path or exchange.in_message.body.get("path")
        if not path:
            raise ValueError("FileDeleteProcessor: path обязателен")
        import shutil

        def _do_delete() -> bool:
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                return True
            except FileNotFoundError:
                if not self.missing_ok:
                    raise
                return False

        deleted = await asyncio.to_thread(_do_delete)
        _rpa_logger.info("file_delete path=%s deleted=%s", path, deleted)
        exchange.in_message.body["deleted"] = deleted
