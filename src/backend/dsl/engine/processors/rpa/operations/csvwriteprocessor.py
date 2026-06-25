"""S171 M6.1 — CsvWriteProcessor (gap fill).

Async CSV write via :mod:`csv` + :func:`asyncio.to_thread`.
Capability: rpa.file.csv.write (medium risk — file creation).
"""
from __future__ import annotations

import asyncio
import csv
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


class CsvWriteProcessor(BaseProcessor):
    """Write list of dicts → CSV file.

    Args:
        dst: Path для output CSV.
        rows: List of dicts (header = keys первого dict).
        delimiter: CSV delimiter (default ``","``).
    """

    required_capability: str | None = "rpa.file.csv.write"
    audit_event: str | None = "rpa.file.csv.write"

    def __init__(
        self,
        *,
        dst: str,
        rows: list[dict[str, Any]],
        delimiter: str = ",",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "csv_write")
        self.dst = dst
        self.rows = rows
        self.delimiter = delimiter

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        if not self.rows:
            await asyncio.to_thread(lambda: open(self.dst, "w", encoding="utf-8").close())
            return

        def _write() -> None:
            keys = list(self.rows[0].keys())
            with open(self.dst, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=keys, delimiter=self.delimiter)
                writer.writeheader()
                writer.writerows(self.rows)

        await asyncio.to_thread(_write)
        _rpa_logger.info("csv_write dst=%s rows=%d", self.dst, len(self.rows))
        exchange.in_message.body["written"] = len(self.rows)
