"""S171 M6.1 — CsvReadProcessor (gap fill).

Async CSV read via :mod:`csv` + :func:`asyncio.to_thread`.
Capability: rpa.file.csv.read (low risk, read-only).
"""
from __future__ import annotations

import asyncio
import csv
import io
from typing import TYPE_CHECKING, Any

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

    required_capability: str | None = "rpa.file.csv.read"
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

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        if self.content is not None:
            text = self.content
        elif self.src:
            import aiofiles

            async with aiofiles.open(self.src, mode="r", encoding="utf-8") as f:
                text = await f.read()
        else:
            raise ValueError("CsvReadProcessor: укажите src или content")

        def _parse() -> list[dict[str, str]]:
            reader = csv.DictReader(io.StringIO(text), delimiter=self.delimiter)
            return list(reader)

        rows = await asyncio.to_thread(_parse)
        _rpa_logger.info("csv_read rows=%d src=%s", len(rows), self.src or "<inline>")
        self.set_result(exchange, self.target, rows)
