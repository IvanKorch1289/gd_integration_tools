"""Экспортёры данных в форматы CSV, Excel, PDF, JSON, Parquet.

Каждый формат — отдельный класс, реализующий ``Exporter[T]``-Protocol
(:mod:`app.core.protocols`), с полями ``format_name`` и ``mime_type``.

Доступ через реестр::

    from src.core.providers_registry import get_provider
    csv_bytes = get_provider("exporter", "csv").export(rows)

Или через универсальный диспатчер :func:`export`, который выбирает экспортёр
по имени формата — удобно для REST/DSL-интеграций, где имя формата приходит
строкой.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any

__all__ = (
    "CsvExporter",
    "ExcelExporter",
    "PdfExporter",
    "JsonExporter",
    "ParquetExporter",
    "export",
    "list_formats",
)

logger = logging.getLogger(__name__)


class CsvExporter:
    """CSV (RFC 4180-совместимый)."""

    format_name = "csv"
    mime_type = "text/csv"

    def get_extension(self) -> str:
        return "csv"

    def export(
        self, data: list[dict[str, Any]], *, options: dict[str, Any] | None = None
    ) -> bytes:
        if not data:
            return b""
        opts = options or {}
        delimiter = opts.get("delimiter", ",")
        encoding = opts.get("encoding", "utf-8")

        buffer = io.StringIO()
        fieldnames = list(data[0].keys())
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        for row in data:
            writer.writerow({k: (v if v is not None else "") for k, v in row.items()})

        raw = buffer.getvalue().encode(encoding)
        logger.info("CSV export: %d rows, %d bytes", len(data), len(raw))
        return raw


class ExcelExporter:
    """XLSX через openpyxl. Автоматически подгоняет ширину колонок."""

    format_name = "xlsx"
    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def get_extension(self) -> str:
        return "xlsx"

    def export(
        self, data: list[dict[str, Any]], *, options: dict[str, Any] | None = None
    ) -> bytes:
        if not data:
            return b""
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise RuntimeError("openpyxl не установлен") from exc

        opts = options or {}
        sheet_name = opts.get("sheet_name", "Data")

        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name

        fieldnames = list(data[0].keys())
        ws.append(fieldnames)
        for row in data:
            ws.append([row.get(k, "") for k in fieldnames])

        # Авто-ширина колонок: max(ширина заголовка, max ширина значения в колонке).
        for col_idx, col_name in enumerate(fieldnames, start=1):
            max_len = max(
                len(str(col_name)),
                max((len(str(row.get(col_name, ""))) for row in data), default=0),
            )
            ws.column_dimensions[
                ws.cell(row=1, column=col_idx).column_letter
            ].width = min(max_len + 2, 50)

        buffer = io.BytesIO()
        wb.save(buffer)
        raw = buffer.getvalue()
        logger.info("Excel export: %d rows, %d bytes", len(data), len(raw))
        return raw


class PdfExporter:
    """PDF через reportlab. Landscape A4, табличный layout."""

    format_name = "pdf"
    mime_type = "application/pdf"

    def get_extension(self) -> str:
        return "pdf"

    def export(
        self, data: list[dict[str, Any]], *, options: dict[str, Any] | None = None
    ) -> bytes:
        if not data:
            return b""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import (
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as exc:
            raise RuntimeError("reportlab не установлен") from exc

        opts = options or {}
        title = opts.get("title", "Report")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements: list[Any] = [Paragraph(title, styles["Heading1"]), Spacer(1, 12)]

        fieldnames = list(data[0].keys())
        table_data: list[list[Any]] = [fieldnames]
        for row in data:
            table_data.append([str(row.get(k, ""))[:80] for k in fieldnames])

        table = Table(table_data)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ]
            )
        )
        elements.append(table)

        doc.build(elements)
        raw = buffer.getvalue()
        logger.info("PDF export: %d rows, %d bytes", len(data), len(raw))
        return raw


class JsonExporter:
    """Pretty-printed JSON (orjson с indent)."""

    format_name = "json"
    mime_type = "application/json"

    def get_extension(self) -> str:
        return "json"

    def export(
        self, data: list[dict[str, Any]], *, options: dict[str, Any] | None = None
    ) -> bytes:
        opts = options or {}
        indent = opts.get("indent", 2)
        # json.dumps для читаемости; orjson медленнее с indent у некоторых версий.
        return json.dumps(data, ensure_ascii=False, indent=indent, default=str).encode(
            "utf-8"
        )


class ParquetExporter:
    """Apache Parquet через pandas + pyarrow."""

    format_name = "parquet"
    mime_type = "application/octet-stream"

    def get_extension(self) -> str:
        return "parquet"

    def export(
        self, data: list[dict[str, Any]], *, options: dict[str, Any] | None = None
    ) -> bytes:
        if not data:
            return b""
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("pandas не установлен") from exc

        df = pd.DataFrame(data)
        buffer = io.BytesIO()
        df.to_parquet(buffer, engine="pyarrow", index=False)
        return buffer.getvalue()


# Реестр экспортёров для быстрого доступа по имени формата.
_EXPORTERS: dict[str, Any] = {
    "csv": CsvExporter(),
    "xlsx": ExcelExporter(),
    "excel": ExcelExporter(),  # alias
    "pdf": PdfExporter(),
    "json": JsonExporter(),
    "parquet": ParquetExporter(),
}


def export(
    format: str, data: list[dict[str, Any]], *, options: dict[str, Any] | None = None
) -> bytes:
    """Универсальный диспатчер по имени формата. Бросает ``KeyError`` если неизвестен."""
    exporter = _EXPORTERS.get(format.lower())
    if exporter is None:
        raise KeyError(f"Неизвестный формат экспорта: {format}")
    return exporter.export(data, options=options)


def list_formats() -> list[str]:
    """Список поддерживаемых форматов экспорта."""
    return sorted(_EXPORTERS.keys())


class ExportFacade:
    """Facade для action-handlers и scheduled_reports.

    Предоставляет async-обёртки ``to_csv/to_excel/to_pdf/to_json/to_parquet``
    поверх синхронных экспортёров — нужны, т.к. ActionHandlerRegistry
    вызывает методы как ``await service.method(...)``.
    """

    async def to_csv(
        self,
        rows: list[dict[str, Any]],
        *,
        delimiter: str = ",",
        encoding: str = "utf-8",
    ) -> bytes:
        return _EXPORTERS["csv"].export(
            rows, options={"delimiter": delimiter, "encoding": encoding}
        )

    async def to_excel(
        self, rows: list[dict[str, Any]], *, sheet_name: str = "Data"
    ) -> bytes:
        return _EXPORTERS["xlsx"].export(rows, options={"sheet_name": sheet_name})

    async def to_pdf(
        self, rows: list[dict[str, Any]], *, title: str = "Report"
    ) -> bytes:
        return _EXPORTERS["pdf"].export(rows, options={"title": title})

    async def to_json(self, rows: list[dict[str, Any]], *, indent: int = 2) -> bytes:
        return _EXPORTERS["json"].export(rows, options={"indent": indent})

    async def to_parquet(self, rows: list[dict[str, Any]]) -> bytes:
        return _EXPORTERS["parquet"].export(rows)


_export_facade = ExportFacade()


def get_export_service() -> ExportFacade:
    """Возвращает async-facade над синхронными экспортёрами.

    Нужен для action-registry и scheduled-reports: callsite'ы вызывают
    ``await service.to_csv(rows)`` — facade даёт именно такой API.
    """
    return _export_facade
