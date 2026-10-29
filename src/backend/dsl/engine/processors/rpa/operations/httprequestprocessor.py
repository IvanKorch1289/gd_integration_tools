"""S171 M6.1 — HttpRequestProcessor (gap fill).

Async HTTP request через :mod:`httpx` (modern async HTTP client,
уже в pyproject deps). Заменяет aiohttp — меньше deps, лучше type hints.

Capability: rpa.http.request (medium risk — network egress).

ADR-0390: размер ответа ограничен (``_MAX_HTTP_RESPONSE_BYTES``) — ответ
целиком попадал в тело exchange'а (и в память процесса).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")

#: Максимальный размер тела ответа (байт) — ADR-0390.
_MAX_HTTP_RESPONSE_BYTES = 32 * 1024 * 1024


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

    required_capability: ClassVar[str | None] = "rpa.http.request"
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

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет HTTP-запрос через httpx и пишет JSON/text-ответ в target."""
        if not await self.auth_check(exchange, action="execute"):
            return
        request_kwargs: dict[str, Any] = {
            "headers": self.headers,
            "timeout": self.timeout,
        }
        if self.body is not None:
            if isinstance(self.body, (dict, list)):
                request_kwargs["json"] = self.body
            else:
                request_kwargs["content"] = str(self.body)

        # S195 fix: use make_http_client facade (WAF + capability gate)
        # вместо raw httpx.AsyncClient. Eliminates inline HTTP bypass.
        from src.backend.core.net.migration_helper import make_http_client

        async with make_http_client(
            timeout=self.timeout, plugin="rpa.httprequestprocessor"
        ) as client:
            fetched = await self._fetch(client, request_kwargs)

        if fetched is None:
            # Превышен лимит ответа — понятная ошибка, ничего не пишем.
            exchange.fail(
                f"http_request blocked: response exceeds "
                f"{_MAX_HTTP_RESPONSE_BYTES} bytes"
            )
            return

        status, response_headers, data = fetched

        _rpa_logger.info(
            "http_request method=%s url=%s status=%d", self.method, self.url, status
        )
        payload: dict[str, Any] = {
            "status": status,
            "headers": response_headers,
            "data": data,
        }
        if self.target == "body":
            # ``BaseProcessor.set_result`` трактует ``"body"`` как имя property
            # (``set_property("body", ...)``) → payload терялся для маршрута.
            # ADR-0369: target ``"body"`` = само тело exchange.
            exchange.in_message.body = payload
            return
        self.set_result(exchange, self.target, payload)

    async def _fetch(
        self, client: Any, request_kwargs: dict[str, Any]
    ) -> tuple[int, dict[str, str], Any] | None:
        """Выполнить запрос и прочитать тело ответа с лимитом размера.

        Для запросов без тела используется streaming-режим клиента — лимит
        проверяется **по ходу** чтения, поэтому oversized-ответ не
        раздувает память процесса. Если клиент не поддерживает streaming
        (legacy/mock) — используется обычный ``request`` с проверкой
        размера после чтения.

        Args:
            client: HTTP-клиент из :func:`make_http_client`.
            request_kwargs: Параметры запроса.

        Returns:
            Кортеж ``(status, headers, data)`` либо ``None``, если размер
            ответа превысил лимит.

        """
        stream_factory = getattr(client, "stream", None)
        if self.body is None and callable(stream_factory):
            async with stream_factory(
                self.method, self.url, headers=self.headers, timeout=self.timeout
            ) as response:
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > _MAX_HTTP_RESPONSE_BYTES:
                        return None
                return (
                    response.status_code,
                    dict(response.headers),
                    self._parse_body(bytes(chunks)),
                )

        response = await client.request(self.method, self.url, **request_kwargs)
        content = response.content
        if isinstance(content, (bytes, bytearray)) and len(content) > (
            _MAX_HTTP_RESPONSE_BYTES
        ):
            return None
        try:
            data = response.json()
        except json.JSONDecodeError, ValueError:
            data = response.text
        return response.status_code, dict(response.headers), data

    @staticmethod
    def _parse_body(raw: bytes) -> Any:
        """Разобрать тело ответа: JSON → объект, иначе текст.

        Args:
            raw: Сырые байты ответа.

        Returns:
            Распарсенный JSON либо декодированный текст.

        """
        try:
            return json.loads(raw)
        except json.JSONDecodeError, ValueError:
            return raw.decode("utf-8", errors="replace")
