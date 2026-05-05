"""Export DSL процессор — экспорт body в CSV/Excel/PDF/JSON/Parquet.

Использует реестр экспортёров :mod:`app.services.io.export_service`
через универсальную функцию :func:`export`, которая сама выбирает класс
по имени формата.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("ExportProcessor",)


class ExportProcessor(BaseProcessor):
    """Экспортирует body (list[dict]) в указанный формат.

    Результат — bytes в ``exchange.properties[output_property]``.
    Поддерживаемые форматы: csv, xlsx/excel, pdf, json, parquet.
    """

    def __init__(
        self,
        format: str = "csv",
        output_property: str = "export_data",
        title: str = "Report",
        name: str | None = None,
    ) -> None:
        super().__init__(name or f"export:{format}")
        self._format = format.lower()
        self._output = output_property
        self._title = title

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.services.io.export_service import export

        body = exchange.in_message.body
        rows = (
            body if isinstance(body, list) else [body] if isinstance(body, dict) else []
        )

        try:
            data = export(self._format, rows, options={"title": self._title})
        except KeyError:
            exchange.set_error(f"Unsupported export format: {self._format}")
            exchange.stop()
            return

        exchange.set_property(self._output, data)
        exchange.set_property(f"{self._output}_size", len(data))
        exchange.set_property(f"{self._output}_format", self._format)
