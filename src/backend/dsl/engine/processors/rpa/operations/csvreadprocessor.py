"""S171 M6.1 — CsvReadProcessor (gap fill).

Async CSV read via :mod:`csv` + :func:`asyncio.to_thread`.
Capability: rpa.file.csv.read (low risk, read-only).

ADR-0367: ``src`` проверяется по path-allowlist (``validate_path``) —
иначе процессор читал произвольный файл ФС.
"""

from __future__ import annotations

import asyncio
import csv
import io
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


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

            async with aiofiles.open(safe_src, encoding="utf-8") as f:
                text = await f.read()
        else:
            raise ValueError("CsvReadProcessor: укажите src или content")

        def _parse() -> list[dict[str, str]]:
            reader = csv.DictReader(io.StringIO(text), delimiter=self.delimiter)
            return list(reader)

        rows = await asyncio.to_thread(_parse)
        _rpa_logger.info("csv_read rows=%d src=%s", len(rows), self.src or "<inline>")
        self.set_result(exchange, self.target, rows)
