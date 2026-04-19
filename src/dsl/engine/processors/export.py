"""Export DSL процессоры — экспорт body в Excel/CSV/PDF."""

from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

__all__ = ("ExportProcessor",)


class ExportProcessor(BaseProcessor):
    """Экспортирует body (list[dict]) в файл указанного формата.

    Результат — bytes в exchange.properties[output_property].
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
        from app.services.export_service import get_export_service

        body = exchange.in_message.body
        rows = body if isinstance(body, list) else [body] if isinstance(body, dict) else []

        svc = get_export_service()

        if self._format == "csv":
            data = await svc.to_csv(rows)
        elif self._format in ("excel", "xlsx"):
            data = await svc.to_excel(rows)
        elif self._format == "pdf":
            data = await svc.to_pdf(rows, title=self._title)
        else:
            exchange.set_error(f"Unsupported export format: {self._format}")
            exchange.stop()
            return

        exchange.set_property(self._output, data)
        exchange.set_property(f"{self._output}_size", len(data))
        exchange.set_property(f"{self._output}_format", self._format)
