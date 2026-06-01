"""Unit-тесты для export.py — ExportProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.export import ExportProcessor


def _make_exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestExportProcessor:
    def test_name_format(self) -> None:
        proc = ExportProcessor(format="csv")
        assert proc.name == "export:csv"

    def test_name_custom(self) -> None:
        proc = ExportProcessor(name="my_export")
        assert proc.name == "my_export"

    def test_format_lowercase(self) -> None:
        proc = ExportProcessor(format="CSV")
        assert proc._format == "csv"

    def test_format_xlsx(self) -> None:
        proc = ExportProcessor(format="xlsx")
        assert proc._format == "xlsx"

    def test_format_excel(self) -> None:
        proc = ExportProcessor(format="excel")
        assert proc._format == "excel"

    def test_format_pdf(self) -> None:
        proc = ExportProcessor(format="pdf")
        assert proc._format == "pdf"

    def test_format_json(self) -> None:
        proc = ExportProcessor(format="json")
        assert proc._format == "json"

    def test_format_parquet(self) -> None:
        proc = ExportProcessor(format="parquet")
        assert proc._format == "parquet"

    def test_output_property_default(self) -> None:
        proc = ExportProcessor()
        assert proc._output == "export_data"

    def test_output_property_custom(self) -> None:
        proc = ExportProcessor(output_property="my_output")
        assert proc._output == "my_output"

    def test_title_default(self) -> None:
        proc = ExportProcessor()
        assert proc._title == "Report"

    def test_title_custom(self) -> None:
        proc = ExportProcessor(title="My Report")
        assert proc._title == "My Report"


class TestExportProcessorProcess:
    @pytest.mark.asyncio
    async def test_process_list_of_dicts(self) -> None:
        proc = ExportProcessor(format="csv")
        ex = _make_exchange(body=[{"name": "Alice", "age": 30}])

        with patch("src.backend.services.io.export_service.export") as mock_export:
            mock_export.return_value = b"csv data"
            await proc.process(ex, MagicMock())

        mock_export.assert_called_once()
        assert ex.properties["export_data"] == b"csv data"
        assert ex.properties["export_data_size"] == len(b"csv data")
        assert ex.properties["export_data_format"] == "csv"

    @pytest.mark.asyncio
    async def test_process_single_dict(self) -> None:
        proc = ExportProcessor(format="csv")
        ex = _make_exchange(body={"name": "Alice", "age": 30})

        with patch("src.backend.services.io.export_service.export") as mock_export:
            mock_export.return_value = b"csv data"
            await proc.process(ex, MagicMock())

        mock_export.assert_called_once()
        # Should be wrapped in list
        call_args = mock_export.call_args
        rows = call_args[0][1]
        assert isinstance(rows, list)

    @pytest.mark.asyncio
    async def test_process_empty_body(self) -> None:
        proc = ExportProcessor(format="csv")
        ex = _make_exchange(body="not a list or dict")

        with patch("src.backend.services.io.export_service.export") as mock_export:
            mock_export.return_value = b""
            await proc.process(ex, MagicMock())

        mock_export.assert_called_once()
        call_args = mock_export.call_args
        rows = call_args[0][1]
        assert rows == []

    @pytest.mark.asyncio
    async def test_process_unsupported_format(self) -> None:
        proc = ExportProcessor(format="unknown")
        ex = _make_exchange(body=[{"key": "value"}])

        with patch("src.backend.services.io.export_service.export") as mock_export:
            mock_export.side_effect = KeyError("Unsupported format")
            await proc.process(ex, MagicMock())

        assert ex.error is not None
        assert "Unsupported export format" in str(ex.error)
        assert ex.stopped is True

    @pytest.mark.asyncio
    async def test_process_sets_properties(self) -> None:
        proc = ExportProcessor(format="xlsx", output_property="my_output")
        ex = _make_exchange(body=[{"col": "val"}])

        with patch("src.backend.services.io.export_service.export") as mock_export:
            mock_export.return_value = b"xlsx bytes"
            await proc.process(ex, MagicMock())

        assert ex.properties["my_output"] == b"xlsx bytes"
        assert ex.properties["my_output_size"] == len(b"xlsx bytes")
        assert ex.properties["my_output_format"] == "xlsx"
