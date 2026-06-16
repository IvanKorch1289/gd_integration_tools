"""Structural protocol for HttpClient mixins."""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class _HttpClientProtocol(Protocol):
    """Common shape expected by HttpClient mixins."""

    settings: Any
    logger: Any
    client: httpx.AsyncClient | None
    last_activity: float
    active_requests: int
    session_lock: Any
    purger_task: Any | None
    _metrics_lock: Any
    circuit_breaker: Any
    metrics: Any

    def _create_new_session(self) -> None: ...

    def _start_purger_if_needed(self) -> None: ...

    async def _close_session(self) -> None: ...

    async def _ensure_session(self) -> None: ...

    async def _log_request(self, **kwargs: Any) -> None: ...

    async def _log_response(self, response: Any, content: Any) -> None: ...

    async def _process_response(
        self, response: Any, response_type: str
    ) -> dict[str, Any]: ...

    async def _build_response_object(
        self, *, response: Any, content: Any, start_time: float
    ) -> dict[str, Any]: ...

    async def _update_metrics(self, *, start_time: float, success: bool) -> None: ...

    async def _handle_final_error(
        self, exc: Exception, start_time: float
    ) -> dict[str, Any]: ...

    def _is_retryable_exception(self, exc: BaseException) -> bool: ...

    async def _prepare_request_kwargs(
        self,
        data: dict[str, Any] | str | bytes | None = None,
        json_data: dict[str, Any] | list[Any] | None = None,
        files: Any | None = None,
    ) -> dict[str, Any]: ...

    async def _build_headers(
        self,
        auth_token: str | None,
        custom_headers: dict[str, str] | None,
        json_data: dict[str, Any] | list[Any] | None,
        data: dict[str, Any] | str | bytes | None,
        files: Any | None,
    ) -> dict[str, str]: ...
