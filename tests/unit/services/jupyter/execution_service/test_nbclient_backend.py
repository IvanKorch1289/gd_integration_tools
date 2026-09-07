"""Тесты NbClientExecutionBackend (T3 ratchet: backend.py 17%→≥90%).

nbclient инжектируется через sys.modules: ImportError-ветка, маппинг
output-типов per cell (stream/execute_result), пропуск markdown,
обёртка исключений в JupyterExecutionError.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.services.jupyter.execution_service.backend import (
    NbClientExecutionBackend,
)
from src.backend.services.jupyter.execution_service.errors import JupyterExecutionError


def _fake_nbclient(execute_side_effect: Exception | None = None) -> MagicMock:
    """Фейковый nbclient: NotebookClient с setup_kernel и управляемыми ячейками."""
    fake = MagicMock()
    cells: list[Any] = [MagicMock() for _ in range(3)]

    stream_out = MagicMock()
    stream_out.output_type = "stream"
    stream_out.name = "stdout"  # NOTE: не kwargs — name служебный у MagicMock
    stream_out.text = "hello\n"
    result_out = MagicMock()
    result_out.output_type = "execute_result"
    result_out.execution_count = 2
    result_out.data = {"text/plain": "2"}
    outputs_by_index: dict[int, list[Any]] = {0: [stream_out], 2: [result_out]}

    def _execute_cell(cell: Any, cell_index: int) -> None:
        # мутация РЕАЛЬНОЙ ячейки nb (как настоящий nbclient)
        cell.outputs = outputs_by_index[cell_index]

    client = MagicMock()
    client.setup_kernel = MagicMock()
    client.execute_cell = MagicMock(side_effect=_execute_cell)
    fake.NotebookClient = MagicMock(return_value=client)
    if execute_side_effect is not None:
        client.setup_kernel = MagicMock(
            side_effect=execute_side_effect,
        )
    fake._cells = cells
    return fake


@pytest.mark.asyncio
async def test_execute_requires_nbclient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """nbclient отсутствует -> JupyterExecutionError с подсказкой установки."""
    monkeypatch.setitem(sys.modules, "nbclient", None)
    backend = NbClientExecutionBackend()
    with pytest.raises(JupyterExecutionError, match="nbclient required"):
        await backend.execute([{"cell_type": "code", "source": "1"}])


@pytest.mark.asyncio
async def test_execute_maps_outputs_and_skips_markdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _fake_nbclient()
    monkeypatch.setitem(sys.modules, "nbclient", fake)
    backend = NbClientExecutionBackend(kernel_name="python3", timeout=30.0)

    results = await backend.execute(
        [
            {"cell_type": "code", "source": "print('hello')"},
            {"cell_type": "markdown", "source": "# md"},
            {"cell_type": "code", "source": "1+1"},
        ],
        notebook_path="local.ipynb",
    )

    assert [r["cell_index"] for r in results] == [0, 2]
    assert results[0]["outputs"] == [
        {"output_type": "stream", "name": "stdout", "text": "hello\n"},
    ]
    assert results[1]["outputs"] == [
        {
            "output_type": "execute_result",
            "execution_count": 2,
            "data": {"text/plain": "2"},
        },
    ]


@pytest.mark.asyncio
async def test_execute_wraps_failure_into_jupyter_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сбой kernel setup -> JupyterExecutionError (обёртка 88-91)."""
    fake = MagicMock()
    client = MagicMock()
    client.setup_kernel = MagicMock(side_effect=RuntimeError("kernel died"))
    fake.NotebookClient = MagicMock(return_value=client)
    monkeypatch.setitem(sys.modules, "nbclient", fake)

    backend = NbClientExecutionBackend()
    with pytest.raises(JupyterExecutionError, match="nbclient execution failed"):
        await backend.execute([{"cell_type": "code", "source": "1"}])
