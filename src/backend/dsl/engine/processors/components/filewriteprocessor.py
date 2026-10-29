"""S65 W1 — FileWriteProcessor extracted from components.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_comp_logger = get_logger("dsl.components")

#: Максимальный размер записываемого файла (байт) — защита от записи
#: неограниченного payload'а на диск (ADR-0390).
_MAX_FILE_WRITE_BYTES = 64 * 1024 * 1024


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
        """Асинхронно записывает тело exchange в файл (JSON/CSV/text/bytes).

        Путь берётся из ``self._path`` или ``self._path_property``. Формат
        определяется автоматически по расширению (``.json``, ``.csv``) или
        явно через ``self._format``. Перед записью путь проходит
        path-traversal валидацию.

        CSV-ветка нейтрализует formula-инъекцию (ADR-0390, канон —
        ``processors/_csv_safety.py``), размер payload'а ограничен
        ``_MAX_FILE_WRITE_BYTES``.

        Args:
            exchange: Текущий exchange; body используется как содержимое файла.
                Результат — в свойстве ``file_written``, путь — в заголовке
                ``CamelFileName``.
            context: Контекст выполнения маршрута.

        """
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
                if len(content) > _MAX_FILE_WRITE_BYTES:
                    exchange.fail(
                        f"File write blocked: payload exceeds "
                        f"{_MAX_FILE_WRITE_BYTES} bytes"
                    )
                    return
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

                from src.backend.dsl.engine.processors._csv_safety import (
                    neutralize_formula,
                )

                # ADR-0390: CSV-ветка нейтрализует formula-инъекцию
                # (канон — processors/_csv_safety.py, ADR-0367). Раньше
                # значения и заголовки писались «как есть» — Excel
                # исполнял их как формулы.
                keys = list(body[0].keys())
                header = [neutralize_formula(k) for k in keys]
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=header)
                writer.writeheader()
                for row in body:
                    writer.writerow(
                        {
                            name: neutralize_formula(row.get(key, ""))
                            for name, key in zip(header, keys, strict=False)
                        }
                    )
                payload = buf.getvalue().encode(self._encoding)
                if len(payload) > _MAX_FILE_WRITE_BYTES:
                    exchange.fail(
                        f"File write blocked: payload exceeds "
                        f"{_MAX_FILE_WRITE_BYTES} bytes"
                    )
                    return
                async with aiofiles.open(path, "wb") as f:
                    await f.write(payload)
            elif isinstance(body, bytes):
                if len(body) > _MAX_FILE_WRITE_BYTES:
                    exchange.fail(
                        f"File write blocked: payload exceeds "
                        f"{_MAX_FILE_WRITE_BYTES} bytes"
                    )
                    return
                async with aiofiles.open(path, "wb") as f:
                    await f.write(body)
            else:
                payload = str(body).encode(self._encoding)
                if len(payload) > _MAX_FILE_WRITE_BYTES:
                    exchange.fail(
                        f"File write blocked: payload exceeds "
                        f"{_MAX_FILE_WRITE_BYTES} bytes"
                    )
                    return
                async with aiofiles.open(path, "wb") as f:
                    await f.write(payload)

            exchange.set_property("file_written", path)
            exchange.in_message.set_header("CamelFileName", path)

        except (PermissionError, OSError) as exc:
            exchange.fail(f"File write failed: {exc}")
