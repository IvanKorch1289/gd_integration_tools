"""S74 W1 — PapermillExecutionBackend: parameterized notebook execution.

FINAL_REPORT_V2 #9 + направление #1: добавить Papermill для
parameterized notebook execution. Papermill extends nbclient with:

* **Template parameters** — ``{{param}}`` placeholders в cells
  (e.g. ``df = pd.read_csv('{{csv_path}}')``)
* **Multi-language cells** — tag cell as ``parameters`` для parameter
  injection
* **Output notebooks** — papermill writes executed notebook to
  ``output_path`` with injected values + execution results

Use case (FINAL_REPORT_V2): A team wants to run a "model training"
notebook daily with different ``date`` / ``model_name`` parameters.
With nbclient (S60 W1), they'd have to programmatically edit the
notebook. With papermill, they submit parameters as dict and papermill
injects them.

Usage::

    backend = PapermillExecutionBackend(kernel_name="python3")
    outputs = await backend.execute_with_params(
        notebook_path="template.ipynb",
        parameters={"date": "2026-06-12", "model_name": "resnet50"},
        output_path="output.ipynb",
    )

Implementation notes:
* ``papermill.execute_notebook`` is sync — we run в
  ``asyncio.to_thread()`` чтобы не block event loop.
* Lazy-import papermill (opt-in extra) — если пакет не установлен,
  ``JupyterExecutionError`` с actionable message.
* Output notebook path writable — caller responsible для cleanup.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("services.jupyter.papermill")

__all__ = ("PapermillExecutionBackend",)


class PapermillExecutionBackend:
    """Papermill-based parameterized notebook execution (S74 W1).

    Limitations:
    * **No async-first API.** Papermill is sync → wrapped в
      ``asyncio.to_thread()``. Throughput OK для single-notebook
      execution; не подходит для high-frequency fan-out (use Hub
      backend для multi-kernel scaling).
    * **Local execution only.** Papermill uses local nbclient kernel —
      НЕ routed через JupyterHub. Use ``HubExecutionBackend`` для
      distributed execution.
    * **No streaming output.** Papermill waits для full execution
      completion. Use ``HubExecutionBackend`` для streaming cell
      output через WebSocket.
    """

    def __init__(
        self,
        kernel_name: str = "python3",
        timeout: float = 600.0,
        progress_bar: bool = False,
    ) -> None:
        self._kernel_name = kernel_name
        self._timeout = timeout
        self._progress_bar = progress_bar

    async def execute_with_params(
        self,
        notebook_path: str,
        parameters: Mapping[str, Any],
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Execute notebook с parameter injection через papermill.

        Args:
            notebook_path: path к template ``.ipynb`` (with ``parameters``
                tag и ``{{param}}`` placeholders).
            parameters: dict of ``{param_name: value}`` для injection.
                Keys must match ``{{key}}`` placeholders в cells.
            output_path: optional output notebook path. Default:
                ``<notebook_stem>_executed.ipynb`` в той же директории.
                Default НЕ очищается автоматически (caller responsible).

        Returns:
            Dict с metadata о execution:
            * ``output_path``: str — actual output path
            * ``parameters_injected``: int — count of params injected
            * ``cells_executed``: int — count of executed cells
            * ``duration_seconds``: float — execution time
            * ``errors``: list[str] — empty if success, else cell errors

        Raises:
            JupyterExecutionError: papermill not installed, or
                execution failed.
            FileNotFoundError: notebook_path не существует.
            PermissionError: output_path не writable.
        """
        if not os.path.exists(notebook_path):
            raise FileNotFoundError(f"Template notebook не найден: {notebook_path}")

        # Lazy-import papermill (opt-in extra).
        try:
            import papermill as pm
            from papermill.exceptions import PapermillExecutionError as PMError
        except ImportError as exc:
            from src.backend.services.jupyter.execution_service.errors import (
                JupyterExecutionError,
            )

            raise JupyterExecutionError(
                "papermill required для parameterized execution. "
                "Install: uv sync --extra jupyter"
            ) from exc

        # Default output path
        if output_path is None:
            stem, ext = os.path.splitext(notebook_path)
            output_path = f"{stem}_executed{ext or '.ipynb'}"

        params_count = len(parameters)
        _logger.info(
            "Papermill execution start: notebook=%s, params=%d, kernel=%s",
            notebook_path,
            params_count,
            self._kernel_name,
        )

        # Sync papermill call в thread (не block event loop).
        loop = asyncio.get_event_loop()
        start = loop.time()
        try:
            await loop.run_in_executor(
                None,
                lambda: pm.execute_notebook(
                    input_path=notebook_path,
                    output_path=output_path,
                    parameters=dict(parameters),
                    kernel_name=self._kernel_name,
                    progress_bar=self._progress_bar,
                    log_output=False,
                ),
            )
        except PMError as exc:
            raise JupyterExecutionError(
                f"Papermill execution failed для {notebook_path}: {exc}"
            ) from exc
        duration = loop.time() - start

        # Read executed notebook для cell count + error collection.
        import nbformat

        nb = nbformat.read(output_path, as_version=4)
        cells_executed = sum(
            1
            for cell in nb.cells
            if cell.cell_type == "code" and cell.get("execution_count")
        )
        errors = [
            f"cell {i}: {cell.get('outputs', [{}])[0].get('ename', '?')}"
            for i, cell in enumerate(nb.cells)
            if cell.cell_type == "code"
            and any(
                out.get("output_type") == "error" for out in cell.get("outputs", [])
            )
        ]

        _logger.info(
            "Papermill execution done: %d cells, %.2fs, %d errors",
            cells_executed,
            duration,
            len(errors),
        )
        return {
            "output_path": output_path,
            "parameters_injected": params_count,
            "cells_executed": cells_executed,
            "duration_seconds": duration,
            "errors": errors,
        }
