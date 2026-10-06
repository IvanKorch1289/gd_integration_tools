"""Hub-run adapter function для DSL ``call_function`` step (S170 NEW).

Позволяет вызывать ``run_hub_notebook`` из YAML без прямого импорта::

    - call_function:
        ref: src.backend.services.jupyter.hub_run_adapter:run
        payload_from: body
        result_property: hub_result

Поддерживает все источники notebook через именованные аргументы::

    run(notebook_name="credit_scoring", parameters={"customer_id": 42})
    run(notebook_path="notebooks/ad_hoc.ipynb")
    run(notebook_content_b64="<base64 .ipynb>")

.. warning:: **Расхождение calling-convention (аудит 2026-10-06).**

    :class:`~src.backend.dsl.engine.processors.function_call.CallFunctionProcessor`
    вызывает цель как ``fn(payload)`` — ОДИН позиционный аргумент, где
    ``payload`` это значение ``payload_from`` (обычно ``exchange.in_message.body``,
    то есть ``dict``). У ``run()`` первый параметр — ``notebook_name: str | None``.

    Поэтому при вызове из YAML тело запроса целиком попадает в
    ``notebook_name``, а не в ``parameters``::

        # так реально вызовется из DSL:
        run({"notebook_name": "credit_scoring", "parameters": {...}})
        # → notebook_name = {"notebook_name": ..., "parameters": {...}}  ← dict в поле str

    Развернуть dict в kwargs невозможно: у процессора параметр
    ``payload_from`` — это ``str``-путь (``"body"`` / ``"body.<field>"`` /
    ``"properties.<name>"``), а не отображение имён.

    **Следствие:** из YAML этот адаптер сейчас непригоден независимо от
    прочих настроек. Маршрут ``routes/jupyter_hub_run/`` поэтому держится
    выключенным (``jupyter_hub_enabled`` default=False).

    **Требуемое решение (ADR, изменение публичной сигнатуры — нужно
    согласование):** принять payload-dict первым позиционным параметром::

        async def run(payload: dict[str, Any] | None = None, **_: Any)

    и разложить его на ``notebook_name`` / ``parameters`` / ``notebook_path``
    / ``notebook_content_b64`` / ``output_path`` / ``user_name``.
    Существующий тест ``tests/unit/services/jupyter/test_hub_run_orchestrator.py::
    TestHubRunAdapter::test_adapter_returns_dict`` вызывает ``run("x", {"a": 1})``
    и обновляется вместе с сигнатурой.
"""

from __future__ import annotations

import base64
from typing import Any

from src.backend.services.jupyter.hub_run_orchestrator import (
    HubRunResult,
    run_hub_notebook,
)


async def run(
    notebook_name: str | None = None,
    parameters: dict[str, Any] | None = None,
    user_name: str = "default",
    notebook_path: str | None = None,
    notebook_content: bytes | None = None,
    notebook_content_b64: str | None = None,
    output_path: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Adapter для DSL call_function → run_hub_notebook.

    Все варианты передачи notebook mutually compatible (см. orchestrator).

    Returns:
        :class:`HubRunResult` как dict.

    """
    content: bytes | None = notebook_content
    if notebook_content_b64 is not None and isinstance(notebook_content_b64, str):
        content = base64.b64decode(notebook_content_b64)

    result: HubRunResult = await run_hub_notebook(
        notebook_name=notebook_name or "inline_notebook",
        parameters=parameters,
        user_name=user_name,
        notebook_content=content,
        notebook_path_override=notebook_path,
        output_path=output_path,
    )
    return {
        "notebook_name": result.notebook_name,
        "notebook_path": result.notebook_path,
        "parameters": result.parameters,
        "outputs": result.outputs,
        "duration_seconds": result.duration_seconds,
        "cells_executed": result.cells_executed,
        "errors": result.errors,
    }


__all__ = ("run",)
