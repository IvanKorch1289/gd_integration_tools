"""S75 W1 — E2BExecutionBackend: cloud sandbox notebook execution.

FINAL_REPORT_V2 #2 + направление #1 (e2b sandbox): безопасное
выполнение untrusted notebooks в облачной sandbox-инфраструктуре
e2b.dev. Backed by ``e2b_code_interpreter`` (Wave 1.7, S1 R-V15-4).

**Design**:
* ``e2b_code_interpreter`` — cloud SDK, opt-in dep (``[ai]`` extra).
* Cell-level execution: ``sandbox.run_code(cell_source, language)`` per
  cell. Sequential execution (E2B kernels are stateful — variables
  persist across run_code calls).
* **Parameters** (papermill-style): cells tagged ``parameters`` →
  injected via ``sandbox.run_code(\"x = {param_value}\")`` prelude.
* **No template placeholders** (e2b не поддерживает ``{{param}}``)
  → manual injection в first parameter cell.
* **Lazy-import** e2b_code_interpreter (opt-in, ~5MB dep).
* **Fail-loud** на missing API key (no silent NoOp fallback в этом
  class — ``E2BSandbox`` (general code) уже имеет ``NoOpSandbox``,
  notebook execution всегда explicit).
* **Polling-based output collection** (e2b sync) — wrapped в
  ``asyncio.to_thread`` (не block event loop).

Use case (FINAL_REPORT_V2 #2): team хочет запускать notebooks с
untrusted code (user-submitted, customer data). Local execution
unsafe (host compromise). E2B provides isolated cloud kernel —
sandbox destroy'ится после execution.

Usage::

    # Production (с real API key)
    backend = E2BExecutionBackend(
        api_key="e2b_...",
        kernel_name="python3",
        timeout=600.0,
    )
    outputs = await backend.execute_with_params(
        notebook_path="customer.ipynb",
        parameters={"date": "2026-06-12"},
    )

    # Without API key → explicit error
    # E2BExecutionError: E2B_API_KEY not set, secure execution disabled.

**Limitations** (docstring):
* No template ``{{param}}`` placeholders (manual injection).
* No streaming output (sandbox.run_code blocking).
* Cloud latency (100-500ms per cell) — не для low-latency workloads.
* E2B quota/API key costs — explicit budget tracking required.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("services.jupyter.e2b")

__all__ = ("E2BExecutionBackend", "E2BExecutionError")


class E2BExecutionError(Exception):
    """S75 W1 — explicit error для E2BExecutionBackend failures.

    Distinct from :class:`JupyterExecutionError` чтобы caller мог
    distinguish cloud-sandbox errors (network/quota/auth) from
    local-notebook errors.
    """


class E2BExecutionBackend:
    """E2B cloud-sandbox notebook execution (S75 W1).

    Attributes:
        api_key: E2B API key (``E2B_API_KEY`` env var).
        kernel_name: kernel language (``python3`` only supported в
            e2b_code_interpreter MVP).
        timeout: per-cell execution timeout (seconds).
        template: E2B template ID (default: ``code-interpreter``).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        kernel_name: str = "python3",
        timeout: float = 600.0,
        template: str = "code-interpreter",
    ) -> None:
        self._api_key = api_key or os.getenv("E2B_API_KEY")
        self._kernel_name = kernel_name
        self._timeout = timeout
        self._template = template

    @property
    def api_key_configured(self) -> bool:
        """True если API key set (existence check, не validity)."""
        return bool(self._api_key)

    async def execute_with_params(
        self,
        notebook_path: str,
        parameters: Mapping[str, Any],
        *,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Execute notebook в E2B cloud sandbox с parameter injection.

        Args:
            notebook_path: path к ``.ipynb`` (local file, uploaded to
                sandbox). Cells tagged ``parameters`` get value injection.
            parameters: dict ``{param_name: value}`` для injection.
            output_path: optional local path для download executed
                ``.ipynb`` (default: ``<stem>_executed.ipynb``).

        Returns:
            Dict с metadata:
            * ``output_path``: str — actual output path
            * ``parameters_injected``: int — count of params injected
            * ``cells_executed``: int — count of executed cells
            * ``duration_seconds``: float
            * ``sandbox_id``: str — E2B sandbox ID (для audit log)
            * ``errors``: list[str]

        Raises:
            E2BExecutionError: API key not set, e2b_code_interpreter
                not installed, или cell execution failed.
            FileNotFoundError: notebook_path не существует.
        """
        if not self._api_key:
            raise E2BExecutionError(
                "E2B_API_KEY not set — secure cloud execution disabled. "
                "Get key: https://e2b.dev/dashboard?tab=keys"
            )
        import os

        if not os.path.exists(notebook_path):
            raise FileNotFoundError(
                f"Notebook не найден: {notebook_path}"
            )

        # Lazy-import papermill для .ipynb parsing
        try:
            import nbformat
        except ImportError as exc:
            raise E2BExecutionError(
                "nbformat required. Install: uv sync --extra jupyter"
            ) from exc

        nb = nbformat.read(notebook_path, as_version=4)
        params_cells = [
            cell
            for cell in nb.cells
            if cell.cell_type == "code"
            and "parameters" in cell.get("metadata", {}).get("tags", [])
        ]
        code_cells = [
            cell
            for cell in nb.cells
            if cell.cell_type == "code"
            and "parameters" not in cell.get("metadata", {}).get("tags", [])
        ]

        params_count = len(parameters)
        _logger.info(
            "E2B execution start: notebook=%s, params=%d, code_cells=%d",
            notebook_path,
            params_count,
            len(code_cells),
        )

        # Sync E2B API → asyncio.to_thread
        loop = asyncio.get_event_loop()
        start = loop.time()
        sandbox_id = ""
        cells_executed = 0
        errors: list[str] = []

        try:
            sandbox_id, cells_executed, errors = await loop.run_in_executor(
                None,
                lambda: self._execute_sync(
                    nb, params_cells, code_cells, parameters
                ),
            )
        except E2BExecutionError:
            raise
        except Exception as exc:
            raise E2BExecutionError(f"E2B execution failed: {exc}") from exc

        duration = loop.time() - start

        # Persist output notebook (optional)
        if output_path is None:
            stem, ext = os.path.splitext(notebook_path)
            output_path = f"{stem}_executed{ext or '.ipynb'}"
        nbformat.write(nb, output_path)

        return {
            "output_path": output_path,
            "parameters_injected": params_count,
            "cells_executed": cells_executed,
            "duration_seconds": duration,
            "sandbox_id": sandbox_id,
            "errors": errors,
        }

    def _execute_sync(
        self,
        nb: Any,
        params_cells: list[Any],
        code_cells: list[Any],
        parameters: Mapping[str, Any],
    ) -> tuple[str, int, list[str]]:
        """Sync E2B execution — run в asyncio.to_thread.

        Returns:
            (sandbox_id, cells_executed, errors).

        Raises:
            E2BExecutionError: sandbox creation failed, cell failed.
        """
        # Lazy-import e2b (opt-in dep)
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError as exc:
            raise E2BExecutionError(
                "e2b_code_interpreter required. Install: uv sync --extra ai"
            ) from exc

        cells_executed = 0
        errors: list[str] = []
        sandbox_id = ""

        # Create sandbox
        try:
            sb = Sandbox.create(
                api_key=self._api_key,
                template=self._template,
                timeout=int(self._timeout),
            )
            sandbox_id = sb.get_info().sandbox_id
        except Exception as exc:  # noqa: BLE001
            raise E2BExecutionError(
                f"E2B sandbox creation failed: {exc}"
            ) from exc

        try:
            # Phase 1: parameter injection (run params_cells first
            # с injected values)
            for cell in params_cells:
                injected_source = self._inject_parameters(
                    cell.source, parameters
                )
                execution = sb.run_code(injected_source)
                if execution.error:
                    errors.append(
                        f"params cell {cells_executed}: "
                        f"{execution.error.name}: {execution.error.value}"
                    )
                cells_executed += 1

            # Phase 2: code cells (sequential, stateful)
            for cell in code_cells:
                execution = sb.run_code(cell.source)
                if execution.error:
                    errors.append(
                        f"code cell {cells_executed}: "
                        f"{execution.error.name}: {execution.error.value}"
                    )
                cells_executed += 1
                # Persist cell output в nb (для output notebook)
                if execution.results:
                    cell.outputs = self._convert_results(execution.results)
                elif execution.logs:
                    cell.outputs = [
                        {
                            "output_type": "stream",
                            "name": "stdout",
                            "text": "\n".join(execution.logs.stdout),
                        }
                    ]
        finally:
            # E2B best practice: always kill sandbox после execution
            try:
                sb.kill()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Failed to kill E2B sandbox: %s", exc)

        return sandbox_id, cells_executed, errors

    @staticmethod
    def _inject_parameters(source: str, parameters: Mapping[str, Any]) -> str:
        """Inject parameter values в parameter cell source.

        Naive strategy: append ``x = value`` lines для each param.
        E2B не поддерживает ``{{param}}`` placeholders (papermill-style).

        Args:
            source: original cell source.
            parameters: dict ``{param_name: value}``.

        Returns:
            New source с parameter assignment lines appended.
        """
        lines = [source, "", "# S75 W1: injected parameters"]
        for key, value in parameters.items():
            # repr() для safe Python literal representation
            lines.append(f"{key} = {value!r}")
        return "\n".join(lines)

    @staticmethod
    def _convert_results(results: list[Any]) -> list[dict[str, Any]]:
        """Convert e2b execution.results → nbformat cell outputs.

        E2B results имеют ``text``/``html``/``png``/``data`` fields.
        Simplified: take first result, wrap в execute_result format.
        """
        if not results:
            return []
        first = results[0]
        if hasattr(first, "text") and first.text:
            return [
                {
                    "output_type": "execute_result",
                    "execution_count": None,
                    "data": {"text/plain": first.text},
                    "metadata": {},
                }
            ]
        return []
