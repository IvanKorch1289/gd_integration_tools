"""S171 M6.1 — CsvReadProcessor (gap fill).

Async CSV read via :mod:`csv` + :func:`asyncio.to_thread`.
Capability: rpa.file.csv.read (low risk, read-only).

ADR-0367: ``src`` проверяется по path-allowlist (``validate_path``) —
иначе процессор читал произвольный файл ФС.

ADR-0390:
* кодировка определяется автоматически (utf-8 → cp1251 → latin-1) — раньше
  жёсткий ``encoding="utf-8"`` ронял чтение cp1251-файла необработанным
  ``UnicodeDecodeError``;
* лимиты: размер файла и количество строк (иначе CSV-бомба съедала память).
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")

#: Максимальный размер CSV-файла (байт) — ADR-0390.
_MAX_CSV_BYTES = 32 * 1024 * 1024

#: Максимальное количество строк в ответе — ADR-0390.
_MAX_CSV_ROWS = 100_000

#: Кодировки в порядке проверки (utf-8-sig снимает BOM).
_CSV_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1251", "latin-1")


def _decode_csv(raw: bytes) -> tuple[str, str]:
    """Определить кодировку CSV-байтов (ADR-0390).

    Args:
        raw: Сырые байты файла.

    Returns:
        Кортеж ``(текст, кодировка)``. ``latin-1`` декодирует любой байт,
        поэтому декодирование всегда успешно.

    """
    for encoding in _CSV_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), "latin-1"


class CsvReadProcessor(BaseProcessor):
    """Read CSV file или inline content → list of dicts.

    Args:
        src: Path to CSV file.
        content: Inline CSV string (альтернатива src).
        delimiter: CSV delimiter (default ``","``).
        to: Куда записать rows (default ``"body.rows"``).

    """

    required_capability: ClassVar[str | None] = "rpa.file.csv.read"
    audit_event: str | None = "rpa.file.csv.read"

    def __init__(
        self,
        *,
        src: str | None = None,
        content: str | None = None,
        delimiter: str = ",",
        to: str = "body.rows",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "csv_read")
        self.src = src
        self.content = content
        self.delimiter = delimiter
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        if not await self.auth_check(exchange, action="read"):
            return
        if self.content is not None:
            text = self.content
            if len(text.encode("utf-8", errors="ignore")) > _MAX_CSV_BYTES:
                exchange.fail(
                    f"csv_read blocked: content exceeds {_MAX_CSV_BYTES} bytes"
                )
                return
        elif self.src:
            # Второй независимый барьер безопасности: capability ограничивает
            # факт вызова, allowlist — путь (иначе читается любой файл ФС).
            from src.backend.dsl.engine.processors._path_safety import (
                PathTraversalError,
                validate_path,
            )

            try:
                safe_src = validate_path(self.src)
            except PathTraversalError as exc:
                exchange.fail(f"csv_read blocked: {exc}")
                return

            import aiofiles

            try:
                size = await asyncio.to_thread(os.path.getsize, safe_src)
            except OSError as exc:
                exchange.fail(f"csv_read failed: {exc}")
                return
            if size > _MAX_CSV_BYTES:
                exchange.fail(
                    f"csv_read blocked: file exceeds {_MAX_CSV_BYTES} bytes "
                    f"(size={size})"
                )
                return

            async with aiofiles.open(safe_src, "rb") as f:
                raw = await f.read()
            text, encoding = _decode_csv(raw)
            if encoding != "utf-8-sig":
                _rpa_logger.info(
                    "csv_read non-utf8 encoding=%s src=%s", encoding, self.src
                )
        else:
            raise ValueError("CsvReadProcessor: укажите src или content")

        def _parse() -> list[dict[str, str]]:
            reader = csv.DictReader(io.StringIO(text), delimiter=self.delimiter)
            rows: list[dict[str, str]] = []
            for row in reader:
                if len(rows) >= _MAX_CSV_ROWS:
                    raise ValueError(
                        f"csv_read: файл содержит больше {_MAX_CSV_ROWS} строк"
                    )
                rows.append(row)
            return rows

        try:
            rows = await asyncio.to_thread(_parse)
        except ValueError as exc:
            exchange.fail(f"csv_read failed: {exc}")
            return
        _rpa_logger.info("csv_read rows=%d src=%s", len(rows), self.src or "<inline>")
        self.set_result(exchange, self.target, rows)
