from __future__ import annotations

"""HttpClient package (S61 W4 decomp from http.py 514 LOC).

17 methods decomposed в 4 mixin files + base.py + factory.py:
- ``session_mixin.py`` (5): _ensure_session, _create_new_session, _start_purger_if_needed, _close_session, _connection_purger
- ``request_mixin.py`` (3): make_request (118 LOC, BIG), _is_retryable_exception, _handle_final_error
- ``prep_mixin.py`` (3): _build_headers, _prepare_request_kwargs, _build_response_object
- ``observability_mixin.py`` (4): _log_request, _log_response, _update_metrics, _process_response
- ``base.py``: FilePart + BaseHttpClient
- ``factory.py``: get_http_client, get_http_client_dependency

Core (2) остается в __init__.py: __init__, close.

Backward-compat: ``from src.backend.infrastructure.clients.transport.http import HttpClient`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

import asyncio

import httpx
from src.backend.core.config.settings import settings
from src.backend.infrastructure.clients.transport.http.base import (
    BaseHttpClient,  # S61 W4: re-export
    FilePart,  # S61 W4: re-export
)
from src.backend.infrastructure.clients.transport.http.factory import (
    get_http_client,  # S61 W4: re-export
    get_http_client_dependency,  # S61 W4: re-export
)
from src.backend.infrastructure.clients.transport.http.observability_mixin import (
    ObservabilityMixin,  # S61 W4: MRO
)
from src.backend.infrastructure.clients.transport.http.prep_mixin import (
    PrepMixin,  # S61 W4: MRO
)
from src.backend.infrastructure.clients.transport.http.request_mixin import (
    RequestMixin,  # S61 W4: MRO
)
from src.backend.infrastructure.clients.transport.http.session_mixin import (
    SessionMixin,  # S61 W4: MRO
)
from src.backend.infrastructure.logging.factory import get_logger

__all__ = (
    "HttpClient",
    "BaseHttpClient",
    "FilePart",
    "get_http_client",
    "get_http_client_dependency",
)


class HttpClient(SessionMixin, RequestMixin, PrepMixin, ObservabilityMixin):
    """HTTP client (4 mixins = 15 methods + 2 core)."""

    __slots__ = (
        "settings",
        "logger",
        "client",
        "last_activity",
        "active_requests",
        "session_lock",
        "_metrics_lock",
        "purger_task",
        "metrics",
    )

    def __init__(self) -> None:

        self.settings = settings.http_base_settings
        self.logger = get_logger("request")

        self.client: httpx.AsyncClient | None = None

        self.last_activity: float = 0.0
        self.active_requests: int = 0
        self.session_lock = asyncio.Lock()
        self._metrics_lock = asyncio.Lock()
        self.purger_task: asyncio.Task | None = None

        self.metrics: dict[str, Any] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0.0,
        }

    async def close(self) -> None:
        try:
            if self.purger_task:
                self.purger_task.cancel()
                try:
                    await self.purger_task
                except asyncio.CancelledError:
                    pass
                self.purger_task = None
            async with self.session_lock:
                await self._close_session()
        except Exception as exc:
            self.logger.error(f"Ошибка закрытия сетевых ресурсов: {exc}", exc_info=True)
