from __future__ import annotations

import asyncio
from time import monotonic
from typing import TYPE_CHECKING, Any

import httpx

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.clients.transport.http._protocol import (
    _HttpClientProtocol,
)


class SessionMixin(_HttpClientProtocol):
    """session lifecycle (ensure, create, purger, close, connection purger) для HttpClient. S61 W4 extraction."""

    __slots__ = ()

    if TYPE_CHECKING:
        purger_task: Any | None

    async def _ensure_session(self) -> None:
        async with self.session_lock:
            now = monotonic()
            if self.client is None or self.client.is_closed:
                self._create_new_session()
                self.logger.debug(
                    "Создана новая HTTP-сессия", extra={"session_id": id(self.client)}
                )
            self.last_activity = now
            self._start_purger_if_needed()

    def _create_new_session(self) -> None:
        limits = httpx.Limits(
            max_connections=self.settings.limit,
            max_keepalive_connections=self.settings.limit_per_host,
            keepalive_expiry=self.settings.keepalive_timeout,
        )
        timeout = httpx.Timeout(
            connect=self.settings.connect_timeout,
            read=self.settings.sock_read_timeout,
            write=self.settings.sock_read_timeout,
            pool=self.settings.total_timeout,
        )
        self.client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            http2=True,
            http1=True,
            verify=bool(self.settings.ssl_verify),
            trust_env=True,
            follow_redirects=True,
        )

    def _start_purger_if_needed(self) -> None:
        if self.purger_task is None or self.purger_task.done():
            self.purger_task = get_task_registry().create_task(
                self._connection_purger(), name="http-client-connection-purger"
            )

    async def _close_session(self) -> None:
        if self.client and not self.client.is_closed:
            await self.client.aclose()
            self.logger.debug(
                "HTTP-сессия закрыта", extra={"session_id": id(self.client)}
            )
        self.client = None

    async def _connection_purger(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.settings.purging_interval)
                if not self.settings.enable_connection_purging:
                    continue
                if self.active_requests != 0:
                    continue
                if monotonic() - self.last_activity > self.settings.keepalive_timeout:
                    async with self.session_lock:
                        await self._close_session()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error(f"Ошибка очистки соединений: {exc}", exc_info=True)
