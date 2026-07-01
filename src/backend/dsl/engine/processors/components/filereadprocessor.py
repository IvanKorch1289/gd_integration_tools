"""S65 W1 — FileReadProcessor extracted from components.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_comp_logger = get_logger("dsl.components")


class FileReadProcessor(BaseProcessor):
    """Camel File Component (read) — read local file into exchange body."""

    def __init__(
        self,
        path: str | None = None,
        *,
        path_property: str | None = None,
        encoding: str = "utf-8",
        binary: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"read_file:{path or 'dynamic'}")
        self._path = path
        self._path_property = path_property
        self._encoding = encoding
        self._binary = binary

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Читает файл с диска (текстовый или бинарный) с проверкой path-traversal и записывает содержимое в exchange."""
        import aiofiles

        from src.backend.dsl.engine.processors._path_safety import (
            PathTraversalError,
            validate_path,
        )

        path = self._path
        if self._path_property:
            path = exchange.properties.get(self._path_property, path)
        if not path:
            body = exchange.in_message.body
            path = body.get("path") if isinstance(body, dict) else str(body)

        if not path:
            exchange.fail("No file path provided")
            return

        try:
            path = validate_path(path)
        except PathTraversalError as exc:
            exchange.fail(f"File read blocked: {exc}")
            return

        try:
            if self._binary:
                async with aiofiles.open(path, "rb") as f:
                    data = await f.read()
            else:
                async with aiofiles.open(path, encoding=self._encoding) as f:
                    data = await f.read()

            exchange.set_out(body=data, headers=dict(exchange.in_message.headers))
            exchange.in_message.set_header("CamelFileName", path)

        except (FileNotFoundError, PermissionError, OSError) as exc:
            exchange.fail(f"File read failed: {exc}")
