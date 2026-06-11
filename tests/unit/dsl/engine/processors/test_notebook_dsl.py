"""Unit-тесты для NotebookDSLProcessor (S43).

Тестирует:
- выполнение notebook с параметрами и экспортом;
- передачу результатов в exchange;
- сериализацию to_spec;
- обработку ошибок.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.notebook_dsl import NotebookDSLProcessor
from src.backend.services.jupyter.execution_service import JupyterExecutionError


def _make_exchange(body: Any = None, properties: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}), properties=properties or {})


class TestNotebookDSLProcessor:
    """Тесты для NotebookDSLProcessor."""

    @pytest.mark.asyncio
    async def test_execute_with_parameters(self) -> None:
        """Успешное выполнение notebook с параметрами."""
        proc = NotebookDSLProcessor(
            notebook_path="extensions/my_plugin/notebooks/analysis.ipynb",
            parameters={"date_range": "2024-01-01:2024-01-31"},
            user_name="alice",
            timeout_seconds=120.0,
        )
        exchange = _make_exchange()

        mock_result = {
            "outputs": [{"cell_index": 0, "outputs": [{"output_type": "stream", "text": "ok"}]}],
        }

        with patch.object(proc._svc, "execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("notebook_outputs") == mock_result["outputs"]
        mock_execute.assert_awaited_once_with(
            notebook_path="extensions/my_plugin/notebooks/analysis.ipynb",
            parameters={"date_range": "2024-01-01:2024-01-31"},
            output_format=None,
            user_name="alice",
            timeout_seconds=120.0,
        )

    @pytest.mark.asyncio
    async def test_execute_without_parameters(self) -> None:
        """Выполнение без параметров — пустой dict по умолчанию."""
        proc = NotebookDSLProcessor(
            notebook_path="analysis.ipynb",
        )
        exchange = _make_exchange()

        mock_result = {"outputs": []}

        with patch.object(proc._svc, "execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("notebook_outputs") == []
        mock_execute.assert_awaited_once_with(
            notebook_path="analysis.ipynb",
            parameters={},
            output_format=None,
            user_name="default",
            timeout_seconds=None,
        )

    @pytest.mark.asyncio
    async def test_execute_with_export(self) -> None:
        """Выполнение с output_format — export_data тоже попадает в exchange."""
        proc = NotebookDSLProcessor(
            notebook_path="report.ipynb",
            output_format="html",
            user_name="bob",
        )
        exchange = _make_exchange()

        mock_result = {
            "outputs": [],
            "export_data": b"<html>report</html>",
            "format": "html",
        }

        with patch.object(proc._svc, "execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = mock_result
            await proc.process(exchange, MagicMock())

        assert exchange.properties.get("notebook_outputs") == []
        assert exchange.properties.get("notebook_export_data") == b"<html>report</html>"
        assert exchange.properties.get("notebook_export_format") == "html"

    @pytest.mark.asyncio
    async def test_execute_failure(self) -> None:
        """Ошибка выполнения — пробрасывается как JupyterExecutionError."""
        proc = NotebookDSLProcessor(
            notebook_path="bad.ipynb",
            parameters={"x": 1},
        )
        exchange = _make_exchange()

        with patch.object(proc._svc, "execute", new_callable=AsyncMock) as mock_execute:
            mock_execute.side_effect = JupyterExecutionError("kernel died")
            with pytest.raises(JupyterExecutionError, match="kernel died"):
                await proc.process(exchange, MagicMock())

    def test_to_spec_full(self) -> None:
        """to_spec возвращает полную спецификацию."""
        proc = NotebookDSLProcessor(
            notebook_path="nb.ipynb",
            parameters={"a": 1},
            output_format="pdf",
            user_name="admin",
            timeout_seconds=30.0,
        )
        spec = proc.to_spec()
        assert spec == {
            "notebook_dsl": {
                "notebook_path": "nb.ipynb",
                "parameters": {"a": 1},
                "output_format": "pdf",
                "user_name": "admin",
                "timeout_seconds": 30.0,
            }
        }

    def test_to_spec_defaults(self) -> None:
        """to_spec не включает дефолтные значения."""
        proc = NotebookDSLProcessor(
            notebook_path="nb.ipynb",
        )
        spec = proc.to_spec()
        assert spec == {
            "notebook_dsl": {
                "notebook_path": "nb.ipynb",
            }
        }
