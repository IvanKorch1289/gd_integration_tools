from __future__ import annotations

from typing import Any



class JupyterExecutionError(Exception):
    """Ошибка выполнения notebook'а через JupyterHub API."""

    def __init__(
        self, message: str, *, status_code: int | None = None, detail: Any = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
