"""Jupyter execution service (Sprint 1).

Notebook execution через JupyterHub REST API + WebSocket kernel channels.
MVP: upload .ipynb → create session → execute cells → collect output.
"""

from __future__ import annotations

from src.backend.core.config.services.jupyter_hub import jupyter_hub_settings
from src.backend.core.di.app_state import app_state_singleton
from src.backend.services.jupyter.execution_service import (
    JupyterExecutionError,
    NotebookExecutionService,
)

__all__ = (
    "JupyterExecutionError",
    "NotebookExecutionService",
    "get_notebook_execution_service",
)


def _default_execution_service_factory() -> NotebookExecutionService:
    """Factory для создания NotebookExecutionService с default settings."""
    return NotebookExecutionService(jupyter_hub_settings)


@app_state_singleton(
    "notebook_execution_service", factory=_default_execution_service_factory
)
def get_notebook_execution_service() -> NotebookExecutionService:  # type: ignore[empty-body]
    """Singleton ``NotebookExecutionService``. Backend подменяется через app.state."""
