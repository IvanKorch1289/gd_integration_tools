from __future__ import annotations

"""Jupyter execution service package (S60 W1 decomp from execution_service.py 571 LOC).

10 methods decomposed в 3 mixin files + 2 helper files (errors + backend):
- ``core_mixin.py`` (1): execute_notebook (78 LOC, BIG)
- ``io_mixin.py`` (3): export_notebook, execute, _build_ipynb
- ``jupyter_mixin.py`` (4): _wait_for_server, _upload_notebook, _create_session, _execute_cell
- ``errors.py``: JupyterExecutionError
- ``backend.py``: NbClientExecutionBackend

Core (2) остается в __init__.py: __init__, _server_to_ws_url.

Backward-compat: ``from src.backend.services.jupyter.execution_service import NotebookExecutionService`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import asyncio
import json
import uuid

import httpx

from src.backend.core.config.services.jupyter_hub import JupyterHubSettings
from src.backend.infrastructure.clients.external.jupyter_hub import JupyterHubClient
from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("services.jupyter.execution")

from src.backend.services.jupyter.execution_service.backend import (
    NbClientExecutionBackend,  # S60 W1: re-export
)
from src.backend.services.jupyter.execution_service.factory import (  # S74 W2
    BackendKind,  # S74 W2: re-export
    ExecutionBackendFactory,  # S74 W2: re-export
)
from src.backend.services.jupyter.execution_service.papermill_backend import (  # S74 W1
    PapermillExecutionBackend,  # S74 W1: re-export
)
from src.backend.services.jupyter.execution_service.core_mixin import (
    CoreMixin,  # S60 W1: MRO
)
from src.backend.services.jupyter.execution_service.errors import (
    JupyterExecutionError,  # S60 W1: re-export
)
from src.backend.services.jupyter.execution_service.io_mixin import (
    IOMixin,  # S60 W1: MRO
)
from src.backend.services.jupyter.execution_service.jupyter_mixin import (
    JupyterBackendMixin,  # S60 W1: MRO
)

__all__ = (
    "BackendKind",  # S74 W2
    "ExecutionBackendFactory",  # S74 W2
    "JupyterExecutionError",
    "NbClientExecutionBackend",
    "NotebookExecutionService",
    "PapermillExecutionBackend",  # S74 W1
)


class NotebookExecutionService(CoreMixin, IOMixin, JupyterBackendMixin):
    """Jupyter notebook execution service (3 mixins = 8 methods + 2 core)."""

    # S74 W4 fix: removed `__slots__ = ()` (S60 W1 decomp forgot про
    # `_settings`/`_hub` instance attrs). Default Python __dict__
    # works correctly. Trade-off: minor memory overhead (single
    # instance per app, negligible).
    def __init__(self, settings: JupyterHubSettings) -> None:
        self._settings = settings
        self._hub = JupyterHubClient(settings)

    @staticmethod
    def _server_to_ws_url(server_url: str) -> str:
        """Convert ``http(s)://host`` to ``ws(s)://host``."""
        if server_url.startswith("https://"):
            return server_url.replace("https://", "wss://", 1)
        return server_url.replace("http://", "ws://", 1)
