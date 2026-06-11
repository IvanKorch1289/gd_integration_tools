"""Notebook Export Processor (Sprint 1).

Экспортирует Jupyter notebook через ``/api/nbconvert`` JupyterHub.
Input: Exchange property ``notebook_path``.
Output: Exchange property ``notebook_export_data`` (bytes) + ``notebook_export_format``.
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

__all__ = ("NotebookExportProcessor",)

_logger = get_logger("dsl.engine.processors.notebook_export")


@processor(
    "notebook_export",
    namespace="core",
    capabilities=("jupyter.export",),
    tags=["jupyter", "export"],
)
class NotebookExportProcessor(BaseProcessor):
    """Export Jupyter notebook to HTML/PDF/Python via JupyterHub.

    Configuration (YAML)::

        steps:
          - processor: notebook_export
            user_name: "alice"
            notebook_path: "analysis.ipynb"
            fmt: "html"

    Input:
        * ``exchange.get_property("notebook_path")`` или ``notebook_path`` из config.

    Output:
        * ``exchange.set_property("notebook_export_data", b"...")``.
        * ``exchange.set_property("notebook_export_format", "html")``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        user_name: str,
        notebook_path: str,
        *,
        fmt: str = "html",
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(name="notebook_export")
        self._user_name = user_name
        self._notebook_path = notebook_path
        self._fmt = fmt
        self._timeout = timeout_seconds
        self._svc = NotebookExecutionService(jupyter_hub_settings)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        path = exchange.get_property("notebook_path") or self._notebook_path

        try:
            data = await self._svc.export_notebook(
                user_name=self._user_name,
                notebook_path=path,
                fmt=self._fmt,
                timeout_seconds=self._timeout,
            )
        except JupyterExecutionError as exc:
            _logger.error("Notebook export failed: %s", exc)
            raise

        exchange.set_property("notebook_export_data", data)
        exchange.set_property("notebook_export_format", self._fmt)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {
            "user_name": self._user_name,
            "notebook_path": self._notebook_path,
            "fmt": self._fmt,
        }
        if self._timeout is not None:
            spec["timeout_seconds"] = self._timeout
        return {"notebook_export": spec}
