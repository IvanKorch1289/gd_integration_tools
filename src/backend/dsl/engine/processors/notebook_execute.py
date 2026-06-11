"""Notebook Execute Processor (Sprint 1).

Выполняет Jupyter notebook через :class:`NotebookExecutionService`.
Input: Exchange с property ``notebook_cells`` (list[dict]) или body (JSON).
Output: Exchange property ``notebook_outputs`` (list[dict]).
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.config.services.jupyter_hub import jupyter_hub_settings
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry.processor import processor
from src.backend.infrastructure.logging.factory import get_logger
from src.backend.services.jupyter.execution_service import (
    JupyterExecutionError,
    NotebookExecutionService,
)

__all__ = ("NotebookExecuteProcessor",)

_logger = get_logger("dsl.engine.processors.notebook_execute")


@processor(
    "notebook_execute",
    namespace="core",
    capabilities=("jupyter.execute",),
    tags=["jupyter", "execution"],
)
class NotebookExecuteProcessor(BaseProcessor):
    """Execute Jupyter notebook cells via JupyterHub.

    Configuration (YAML)::

        steps:
          - processor: notebook_execute
            user_name: "alice"
            notebook_path: "analysis.ipynb"
            timeout_seconds: 60.0

    Input:
        * ``exchange.get_property("notebook_cells")`` — list of cell dicts.
        * Fallback: ``exchange.in_message.body`` parsed as JSON list.

    Output:
        * ``exchange.set_property("notebook_outputs", [...])``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        user_name: str,
        notebook_path: str,
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(name="notebook_execute")
        self._user_name = user_name
        self._notebook_path = notebook_path
        self._timeout = timeout_seconds
        self._svc = NotebookExecutionService(jupyter_hub_settings)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        cells = exchange.get_property("notebook_cells")
        if cells is None:
            try:
                body = exchange.in_message.body
                cells = body if isinstance(body, list) else []
            except Exception:
                cells = []

        if not cells:
            _logger.warning("No notebook cells to execute")
            exchange.set_property("notebook_outputs", [])
            return

        try:
            outputs = await self._svc.execute_notebook(
                user_name=self._user_name,
                notebook_path=self._notebook_path,
                cells=cells,
                timeout_seconds=self._timeout,
            )
        except JupyterExecutionError as exc:
            _logger.error("Notebook execution failed: %s", exc)
            raise

        exchange.set_property("notebook_outputs", outputs)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {
            "user_name": self._user_name,
            "notebook_path": self._notebook_path,
        }
        if self._timeout is not None:
            spec["timeout_seconds"] = self._timeout
        return {"notebook_execute": spec}
