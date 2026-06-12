"""Notebook DSL Processor (S43).

Выполняет локальный Jupyter notebook через :class:`NotebookExecutionService`
с поддержкой параметров и опционального экспорта.

Input:  Конфигурация ``notebook_path``, ``parameters``, ``output_format``.
Output: Exchange properties ``notebook_outputs``, ``notebook_export_data`` (optional),
        ``notebook_export_format`` (optional).
"""

from __future__ import annotations

from typing import Any, ClassVar

from src.backend.core.config.services.jupyter_hub import jupyter_hub_settings
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry.processor import processor
from src.backend.core.logging import get_logger
from src.backend.services.jupyter.execution_service import (
    JupyterExecutionError,
    NotebookExecutionService,
)

__all__ = ("NotebookDSLProcessor",)

_logger = get_logger("dsl.engine.processors.notebook_dsl")


@processor(
    "notebook_dsl",
    namespace="core",
    capabilities=("jupyter.execute",),
    tags=["jupyter", "dsl"],
)
class NotebookDSLProcessor(BaseProcessor):
    """Execute local Jupyter notebook with parameters via JupyterHub.

    Configuration (YAML)::

        steps:
          - processor: notebook_dsl
            notebook_path: "extensions/my_plugin/notebooks/analysis.ipynb"
            parameters:
              date_range: "2024-01-01:2024-01-31"
            output_format: "html"
            user_name: "alice"
            timeout_seconds: 60.0

    Output:
        * ``exchange.set_property("notebook_outputs", [...])``.
        * ``exchange.set_property("notebook_export_data", b"...")`` (if ``output_format``).
        * ``exchange.set_property("notebook_export_format", "html")`` (if ``output_format``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        notebook_path: str,
        *,
        parameters: dict[str, Any] | None = None,
        output_format: str | None = None,
        user_name: str = "default",
        timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(name="notebook_dsl")
        self._notebook_path = notebook_path
        self._parameters = dict(parameters) if parameters else {}
        self._output_format = output_format
        self._user_name = user_name
        self._timeout = timeout_seconds
        self._svc = NotebookExecutionService(jupyter_hub_settings)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            result = await self._svc.execute(
                notebook_path=self._notebook_path,
                parameters=self._parameters,
                output_format=self._output_format,
                user_name=self._user_name,
                timeout_seconds=self._timeout,
            )
        except JupyterExecutionError as exc:
            _logger.error("Notebook DSL execution failed: %s", exc)
            raise

        exchange.set_property("notebook_outputs", result.get("outputs"))
        if self._output_format:
            exchange.set_property("notebook_export_data", result.get("export_data"))
            exchange.set_property("notebook_export_format", self._output_format)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"notebook_path": self._notebook_path}
        if self._parameters:
            spec["parameters"] = dict(self._parameters)
        if self._output_format:
            spec["output_format"] = self._output_format
        if self._user_name != "default":
            spec["user_name"] = self._user_name
        if self._timeout is not None:
            spec["timeout_seconds"] = self._timeout
        return {"notebook_dsl": spec}
