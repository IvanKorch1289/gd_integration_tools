"""S171 M6.1 — HttpRequestProcessor (gap fill).

Async HTTP request через :mod:`aiohttp` (асинхронный HTTP client).
Capability: rpa.http.request (medium risk — network egress).
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

# Module-level import (not lazy) for patchability in tests.
# aiohttp is heavy — only import here at module-load time.
import aiohttp  # noqa: E402

_rpa_logger = get_logger("dsl.rpa")


class HttpRequestProcessor(BaseProcessor):
    """Async HTTP request (GET/POST/PUT/DELETE/PATCH).

    Args:
        method: HTTP method.
        url: Target URL.
        headers: Request headers (dict).
        body: Request body (dict → JSON, str → raw).
        timeout: Request timeout seconds (default 30).
        to: Куда записать ``{status, headers, data}`` (default ``"body"``).
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
        request_kwargs: dict[str, Any] = {
            "headers": self.headers,
            "timeout": aiohttp.ClientTimeout(total=self.timeout),
        }
        if self.body is not None:
            if isinstance(self.body, (dict, list)):
                request_kwargs["json"] = self.body
            else:
                request_kwargs["data"] = str(self.body)

        async with aiohttp.ClientSession() as session:
            async with session.request(
                self.method, self.url, **request_kwargs
            ) as resp:
                text = await resp.text()
                try:
                    data = json.loads(text)
                except (json.JSONDecodeError, ValueError):
                    data = text

        _rpa_logger.info(
            "http_request method=%s url=%s status=%d",
            self.method, self.url, resp.status,
        )
        self.set_result(exchange, self.target, {
            "status": resp.status,
            "headers": dict(resp.headers),
            "data": data,
        })
