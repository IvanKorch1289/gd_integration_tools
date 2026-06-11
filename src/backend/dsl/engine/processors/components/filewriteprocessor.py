from __future__ import annotations
"""S65 W1 — FileWriteProcessor extracted from components.py.

Per-processor file split.
"""

import contextlib
from collections.abc import Callable
from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor


_comp_logger = get_logger("dsl.components")




class FileWriteProcessor(BaseProcessor):
    """Camel File Component (write) — write exchange body to local file."""

    def __init__(
        self,
        path: str | None = None,
        *,
        path_property: str | None = None,
        format: str = "auto",
        encoding: str = "utf-8",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"write_file:{path or 'dynamic'}")
        self._path = path
        self._path_property = path_property
        self._format = format
        self._encoding = encoding

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import aiofiles

        from src.backend.dsl.engine.processors._path_safety import (
            PathTraversalError,
            validate_path,
        )

        path = self._path
        if self._path_property:
            path = exchange.properties.get(self._path_property, path)

        if not path:
            exchange.fail("No file path provided for write")
            return

        try:
            path = validate_path(path)
        except PathTraversalError as exc:
            exchange.fail(f"File write blocked: {exc}")
            return

        body = exchange.in_message.body
        fmt = self._format

        if fmt == "auto":
            if path.endswith(".json"):
                fmt = "json"
            elif path.endswith(".csv"):
                fmt = "csv"
            else:
                fmt = "text"

        try:
            if fmt == "json":
                content = orjson.dumps(body, default=str, option=orjson.OPT_INDENT_2)
                async with aiofiles.open(path, "wb") as f:
                    await f.write(content)
            elif (
                fmt == "csv"
                and isinstance(body, list)
                and body
                and isinstance(body[0], dict)
            ):
                import csv
                import io

                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=body[0].keys())
                writer.writeheader()
                writer.writerows(body)
                async with aiofiles.open(path, "w", encoding=self._encoding) as f:
                    await f.write(buf.getvalue())
            elif isinstance(body, bytes):
                async with aiofiles.open(path, "wb") as f:
                    await f.write(body)
            else:
                async with aiofiles.open(path, "w", encoding=self._encoding) as f:
                    await f.write(str(body))

            exchange.set_property("file_written", path)
            exchange.in_message.set_header("CamelFileName", path)

        except (PermissionError, OSError) as exc:
            exchange.fail(f"File write failed: {exc}")
