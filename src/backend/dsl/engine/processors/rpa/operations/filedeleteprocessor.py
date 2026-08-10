"""S171 M6 — FileDeleteProcessor (gap fill).

Безопасное удаление файла/директории.
Капабилити: rpa.file.delete (RCE-shaped).
"""
from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, ClassVar

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

    required_capability: ClassVar[str | None] = "rpa.file.delete"
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
        self, exchange: Exchange[Any], context: ExecutionContext,
    ) -> None:
        """Метод process (см. signature)."""
        if not await self.auth_check(exchange, action="write"):
            return
        path = self.path or exchange.in_message.body.get("path")
        if not path:
            raise ValueError("FileDeleteProcessor: path обязателен")
        # Bug fix (cycle 33): Path-traversal guard before deletion.
        # Without this, a caller with capability ``rpa.file.delete`` could
        # delete arbitrary directories via ``../../etc`` payloads.
        from src.backend.dsl.engine.processors._path_safety import (
            PathTraversalError,
            validate_path,
        )

        try:
            safe_path = validate_path(path)
        except PathTraversalError as exc:
            exchange.fail(f"path_traversal_blocked: {exc}")
            return

        import shutil

        def _do_delete() -> bool:
            try:
                if os.path.isdir(safe_path) and not os.path.islink(safe_path):
                    shutil.rmtree(safe_path)
                else:
                    os.remove(safe_path)
                return True
            except FileNotFoundError:
                if not self.missing_ok:
                    raise
                return False

        deleted = await asyncio.to_thread(_do_delete)
        _rpa_logger.info("file_delete path=%s deleted=%s", safe_path, deleted)
        self.set_result(exchange, "body.deleted", deleted)
