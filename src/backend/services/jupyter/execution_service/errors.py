from __future__ import annotations
import asyncio
import json
import uuid
from typing import Any

import httpx

from src.backend.core.config.services.jupyter_hub import JupyterHubSettings
from src.backend.infrastructure.clients.external.jupyter_hub import JupyterHubClient
from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger("services.jupyter.execution")

class JupyterExecutionError(Exception):
    """Ошибка выполнения notebook'а через JupyterHub API."""

    def __init__(
        self, message: str, *, status_code: int | None = None, detail: Any = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
