"""Focused tests for export_service exporters (PERF-6.6 Sprint 16 coverage ratchet).

Coverage target: export_service.py 30% → 70%+.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.backend.services.io.export_service import (
    CsvExporter,
    ExcelExporter,
    ExportFacade,
    JsonExporter,
    PdfExporter,
    list_formats,
)


def test_list_formats_returns_supported() -> None:
    """list_formats() returns list of supported format strings."""
    formats = list_formats()
    assert "csv" in formats
    assert "xlsx" in formats
    assert "json" in formats
    assert "pdf" in formats


def test_list_formats_unique() -> None:
    """list_formats() returns unique values."""
    formats = list_formats()
    assert len(formats) == len(set(formats))


def test_csv_exporter_get_extension() -> None:
    """CsvExporter.get_extension() == 'csv'."""
    assert CsvExporter().get_extension() == "csv"


def test_csv_exporter_export_dataframe() -> None:
    """CsvExporter.export() возвращает CSV bytes."""
    data = [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]
    result = CsvExporter().export(data)
    assert b"a,b" in result
    assert b"1,x" in result


def test_excel_exporter_get_extension() -> None:
    """ExcelExporter.get_extension() == 'xlsx'."""
    assert ExcelExporter().get_extension() == "xlsx"


def test_excel_exporter_export_dataframe() -> None:
    """ExcelExporter.export() returns xlsx bytes (ZIP 'PK' magic)."""
    data = [{"col": 1}, {"col": 2}]
    result = ExcelExporter().export(data)
    assert result[:2] == b"PK"


def test_json_exporter_get_extension() -> None:
    """JsonExporter.get_extension() == 'json'."""
    assert JsonExporter().get_extension() == "json"


def test_json_exporter_export_dataframe() -> None:
    """JsonExporter.export(DataFrame) → JSON records orient."""
    data = [{"a": 1, "b": 3}, {"a": 2, "b": 4}]
    result = JsonExporter().export(data)
    parsed = json.loads(result.decode("utf-8"))
    assert parsed == [{"a": 1, "b": 3}, {"a": 2, "b": 4}]


def test_pdf_exporter_get_extension() -> None:
    """PdfExporter.get_extension() == 'pdf'."""
    assert PdfExporter().get_extension() == "pdf"



def test_pdf_exporter_get_extension_only() -> None:
    """PDF export test skipped — requires reportlab (not in test deps)."""
    assert PdfExporter().get_extension() == "pdf"
