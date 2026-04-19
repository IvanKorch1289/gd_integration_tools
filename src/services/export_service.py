"""Export Service — экспорт данных в Excel, CSV, PDF.

Доступ через:
- REST: POST /api/v1/export/excel|csv|pdf
- Queue: action "export.to_excel|csv|pdf"
- DSL: .export(format) fluent method
- Prefect: export task
"""

from __future__ import annotations

import csv
import io
import logging
from typing import Any

from app.core.decorators.singleton import singleton

__all__ = ("ExportService", "get_export_service")

logger = logging.getLogger(__name__)


@singleton
class ExportService:
    """Экспорт данных в различные форматы."""

    async def to_csv(
        self,
        rows: list[dict[str, Any]],
        delimiter: str = ",",
        encoding: str = "utf-8",
    ) -> bytes:
        """Экспорт в CSV."""
        if not rows:
            return b""

        buffer = io.StringIO()
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (v if v is not None else "") for k, v in row.items()})

        data = buffer.getvalue().encode(encoding)
        logger.info("CSV export: %d rows, %d bytes", len(rows), len(data))
        return data

    async def to_excel(
        self,
        rows: list[dict[str, Any]],
        sheet_name: str = "Data",
    ) -> bytes:
        """Экспорт в Excel (XLSX)."""
        if not rows:
            return b""

        try:
            from openpyxl import Workbook
        except ImportError:
            raise RuntimeError("openpyxl не установлен. Установите: pip install openpyxl")

        wb = Workbook()
        ws = wb.active
        ws.title = sheet_name

        fieldnames = list(rows[0].keys())
        ws.append(fieldnames)
        for row in rows:
            ws.append([row.get(k, "") for k in fieldnames])

        # Auto-size columns
        for col_idx, col_name in enumerate(fieldnames, start=1):
            max_len = max(
                len(str(col_name)),
                max((len(str(row.get(col_name, ""))) for row in rows), default=0),
            )
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = (
                min(max_len + 2, 50)
            )

        buffer = io.BytesIO()
        wb.save(buffer)
        data = buffer.getvalue()
        logger.info("Excel export: %d rows, %d bytes", len(rows), len(data))
        return data

    async def to_pdf(
        self,
        rows: list[dict[str, Any]],
        title: str = "Report",
    ) -> bytes:
        """Экспорт в PDF."""
        if not rows:
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
        except ImportError:
            raise RuntimeError("reportlab не установлен. Установите: pip install reportlab")

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
        styles = getSampleStyleSheet()
        elements: list[Any] = [
            Paragraph(title, styles["Heading1"]),
            Spacer(1, 12),
        ]

        fieldnames = list(rows[0].keys())
        table_data: list[list[Any]] = [fieldnames]
        for row in rows:
            table_data.append([str(row.get(k, ""))[:80] for k in fieldnames])

        table = Table(table_data)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ]))
        elements.append(table)

        doc.build(elements)
        data = buffer.getvalue()
        logger.info("PDF export: %d rows, %d bytes", len(rows), len(data))
        return data


def get_export_service() -> ExportService:
    return ExportService()
