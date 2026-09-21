"""Unit-тесты для NotebookExecuteProcessor и NotebookExportProcessor (Sprint 1).

Тестирует:
- выполнение ячеек notebook через NotebookExecutionService (mock)
- экспорт notebook в различные форматы
- обработку ошибок
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.notebook_execute import NotebookExecuteProcessor
from src.backend.dsl.engine.processors.notebook_export import NotebookExportProcessor


def _make_exchange(
    body: Any = None, properties: dict[str, Any] | None = None
) -> Exchange[Any]:
    return Exchange(
        in_message=Message(body=body, headers={}), properties=properties or {}
    )


class TestNotebookExecuteProcessor:
    """Тесты для NotebookExecuteProcessor."""

    @pytest.mark.asyncio
    async def test_notebook_execute_cells(self) -> None:
        """Успешное выполнение ячеек notebook."""
        proc = NotebookExecuteProcessor(
            user_name="alice", notebook_path="analysis.ipynb", timeout_seconds=60.0
        )
        exchange = _make_exchange()
        exchange.set_property(
            "notebook_cells", [{"cell_type": "code", "source": "print(1+1)"}]
        )

        mock_outputs = [
            {"cell_index": 0, "outputs": [{"output_type": "stream", "text": "2\n"}]}
        ]

        proc._svc = MagicMock()
        with patch.object(
            proc._svc, "execute_notebook", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = mock_outputs
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("notebook_outputs") == mock_outputs
        mock_execute.assert_awaited_once_with(
            user_name="alice",
            notebook_path="analysis.ipynb",
            cells=[{"cell_type": "code", "source": "print(1+1)"}],
            timeout_seconds=60.0,
        )

    @pytest.mark.asyncio
    async def test_notebook_execute_empty_cells(self) -> None:
        """Пустой список ячеек — пустой результат."""
        proc = NotebookExecuteProcessor(
            user_name="alice", notebook_path="analysis.ipynb"
        )
        exchange = _make_exchange()

        await proc.process(exchange, MagicMock())

        assert exchange.properties.get("notebook_outputs") == []

    @pytest.mark.asyncio
    async def test_notebook_execute_from_body(self) -> None:
        """Ячейки из exchange body."""
        proc = NotebookExecuteProcessor(user_name="bob", notebook_path="test.ipynb")
        exchange = _make_exchange(body=[{"cell_type": "code", "source": "1+1"}])

        mock_outputs = [{"cell_index": 0, "outputs": []}]

        proc._svc = MagicMock()
        with patch.object(
            proc._svc, "execute_notebook", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = mock_outputs
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("notebook_outputs") == mock_outputs

    @pytest.mark.asyncio
    async def test_notebook_execute_failure(self) -> None:
        """Ошибка выполнения — пробрасывается."""
        proc = NotebookExecuteProcessor(
            user_name="alice", notebook_path="analysis.ipynb"
        )
        exchange = _make_exchange()
        exchange.set_property(
            "notebook_cells", [{"cell_type": "code", "source": "raise"}]
        )

        from src.backend.services.jupyter.execution_service import JupyterExecutionError

        proc._svc = MagicMock()
        with patch.object(
            proc._svc, "execute_notebook", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.side_effect = JupyterExecutionError("kernel died")
            with pytest.raises(JupyterExecutionError, match="kernel died"):
                await proc.process(exchange, MagicMock())


class TestNotebookExportProcessor:
    """Тесты для NotebookExportProcessor."""

    @pytest.mark.asyncio
    async def test_notebook_export_html(self) -> None:
        """Экспорт в HTML."""
        proc = NotebookExportProcessor(
            user_name="alice", notebook_path="analysis.ipynb", fmt="html"
        )
        exchange = _make_exchange()

        proc._svc = MagicMock()
        with patch.object(
            proc._svc, "export_notebook", new_callable=AsyncMock
        ) as mock_export:
            mock_export.return_value = b"<html>hello</html>"
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("notebook_export_data") == b"<html>hello</html>"
        assert exchange.properties.get("notebook_export_format") == "html"
        mock_export.assert_awaited_once_with(
            user_name="alice",
            notebook_path="analysis.ipynb",
            fmt="html",
            timeout_seconds=None,
        )

    @pytest.mark.asyncio
    async def test_notebook_export_from_property(self) -> None:
        """Путь к notebook из exchange property."""
        proc = NotebookExportProcessor(
            user_name="bob", notebook_path="default.ipynb", fmt="pdf"
        )
        exchange = _make_exchange()
        exchange.set_property("notebook_path", "override.ipynb")

        proc._svc = MagicMock()
        with patch.object(
            proc._svc, "export_notebook", new_callable=AsyncMock
        ) as mock_export:
            mock_export.return_value = b"%PDF-1.4"
            await proc.process(exchange, MagicMock())

        mock_export.assert_awaited_once_with(
            user_name="bob",
            notebook_path="override.ipynb",
            fmt="pdf",
            timeout_seconds=None,
        )
