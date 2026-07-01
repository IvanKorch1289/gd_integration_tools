"""S171 M6.1 — HttpRequestProcessor (gap fill).

Async HTTP request через :mod:`httpx` (modern async HTTP client,
уже в pyproject deps). Заменяет aiohttp — меньше deps, лучше type hints.

Capability: rpa.http.request (medium risk — network egress).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")


class HttpRequestProcessor(BaseProcessor):
    """Async HTTP request (GET/POST/PUT/DELETE/PATCH).

    Args:
        method: HTTP method.
        url: Target URL.
        headers: Request headers (dict).
        body: Request body (dict → JSON, str → raw).
        timeout: Request timeout seconds (default 30).
        to: Куда записать ``{status, headers, data}``.
    """

    required_capability: str | None = "rpa.http.request"
    audit_event: str | None = "rpa.http.request"

    def __init__(
        self,
        *,
        method: str = "GET",
        url: str,
        headers: dict[str, str] | None = None,
        body: Any = None,
        timeout: float = 30.0,
        to: str = "body",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"http_{method.lower()}:{url[:30]}")
        self.method = method.upper()
        self.url = url
        self.headers = headers or {}
        self.body = body
        self.timeout = timeout
        self.target = to

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Выполняет HTTP-запрос через httpx и пишет JSON/text-ответ в target."""
        request_kwargs: dict[str, Any] = {
            "headers": self.headers,
            "timeout": self.timeout,
        }
        if self.body is not None:
            if isinstance(self.body, (dict, list)):
                request_kwargs["json"] = self.body
            else:
                request_kwargs["content"] = str(self.body)

        async with httpx.AsyncClient() as client:
            response = await client.request(
                self.method, self.url, **request_kwargs
            )

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            data = response.text

        _rpa_logger.info(
            "http_request method=%s url=%s status=%d",
            self.method, self.url, response.status_code,
        )
        self.set_result(exchange, self.target, {
            "status": response.status_code,
            "headers": dict(response.headers),
            "data": data,
        })
