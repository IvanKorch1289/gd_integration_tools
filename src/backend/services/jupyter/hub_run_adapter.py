"""Hub-run adapter function для DSL ``call_function`` step (S170 NEW).

Позволяет вызывать ``run_hub_notebook`` из YAML без прямого импорта::

    - call_function:
        ref: services.jupyter.hub_run_adapter:run
        kwargs_from: body
        result_property: hub_result

Поддерживает все источники notebook через kwargs::

    - call_function:
        ref: services.jupyter.hub_run_adapter:run
        kwargs:
          notebook_name: credit_scoring
          parameters: {customer_id: 42}
          # OR
          notebook_path: notebooks/ad_hoc.ipynb
          # OR
          notebook_content_b64: <base64 .ipynb>
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
