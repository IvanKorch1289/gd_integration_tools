"""Structural protocol for NotebookExecutionService mixins.

Sprint 36 (tech-debt): объявляет cross-mixin атрибуты и методы, чтобы
mypy видел ``self._settings``, ``self._hub``, ``self._execute_cell`` и т.д.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.backend.core.clients.jupyter_hub import JupyterHubClient
from src.backend.core.config.services.jupyter_hub import JupyterHubSettings


class _NotebookExecutionProtocol(Protocol):
    """Общий контракт для CoreMixin / IOMixin / JupyterBackendMixin."""

    _settings: JupyterHubSettings
    _hub: JupyterHubClient

    async def execute_notebook(
        self,
        user_name: str,
        notebook_path: str,
        cells: list[dict[str, Any]],
        *,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]: ...

    async def export_notebook(
        self,
        user_name: str,
        notebook_path: str,
        *,
        fmt: str = "html",
        timeout_seconds: float | None = None,
    ) -> bytes: ...

    @staticmethod
    def _server_to_ws_url(server_url: str) -> str: ...

    async def _wait_for_server(
        self, user_name: str, *, timeout: float, interval: float = 1.0
    ) -> Any: ...

    async def _upload_notebook(
        self, server_url: str, path: str, content: dict[str, Any]
    ) -> None: ...

    async def _create_session(
        self, server_url: str, notebook_path: str
    ) -> dict[str, Any]: ...

    async def _execute_cell(
        self, server_url: str, kernel_id: str, source: str, *, timeout: float
    ) -> list[dict[str, Any]]: ...

    @staticmethod
    def _build_ipynb(notebook_path: str, cells: list[dict[str, Any]]) -> Any: ...
