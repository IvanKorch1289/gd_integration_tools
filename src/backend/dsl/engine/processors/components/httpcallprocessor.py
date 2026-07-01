"""S65 W1 — HttpCallProcessor extracted from components.py.

Per-processor file split.
"""

from __future__ import annotations

import contextlib
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_comp_logger = get_logger("dsl.components")


class HttpCallProcessor(BaseProcessor):
    """Camel HTTP Component — call external APIs from DSL pipeline.

    Supports GET/POST/PUT/DELETE with headers, auth, and timeout.
    """

    def __init__(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        body_from_exchange: bool = True,
        result_property: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"http:{method}:{url[:40]}")
        self._url = url
        self._method = method.upper()
        self._headers = headers or {}
        self._auth_token = auth_token
        self._timeout = timeout
        self._body_from_exchange = body_from_exchange
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет HTTP-запрос через общий http-клиент и пишет ответ в exchange."""
        from src.backend.infrastructure.clients.transport.http import (
            get_http_client_dependency,
        )

        client = get_http_client_dependency()

        json_body = None
        if self._method in ("POST", "PUT", "PATCH") and self._body_from_exchange:
            body = exchange.in_message.body
            if isinstance(body, dict):
                json_body = body

        url = self._url
        if "{" in url and isinstance(exchange.in_message.body, dict):
            with contextlib.suppress(KeyError, IndexError):
                url = url.format(**exchange.in_message.body)

        try:
            result = await client.make_request(
                method=self._method,
                url=url,
                headers=self._headers or None,
                json=json_body,
                auth_token=self._auth_token,
                total_timeout=self._timeout,
            )

            if self._result_property:
                exchange.set_property(self._result_property, result)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

        except Exception as exc:
            exchange.fail(f"HTTP {self._method} {url} failed: {exc}")
