"""Middleware для HTTP-кэширования GET-ответов.

Добавляет заголовки ETag и Cache-Control к GET-ответам
с Content-Type: application/json. Поддерживает условные
запросы через If-None-Match.
"""

import hashlib

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from app.utilities.utils import AsyncChunkIterator

__all__ = ("ResponseCacheMiddleware",)


class ResponseCacheMiddleware(BaseHTTPMiddleware):
    """HTTP-кэширование GET-ответов через ETag."""

    def __init__(self, app: ASGIApp, max_age: int = 60) -> None:
        super().__init__(app)
        self._max_age = max_age

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method != "GET":
            return await call_next(request)

        response = await call_next(request)

        if response.status_code != 200:
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = await self._capture_body(response)
        etag = f'"{hashlib.md5(body).hexdigest()}"'  # noqa: S324

        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match == etag:
            return Response(status_code=304, headers={"ETag": etag})

        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = f"public, max-age={self._max_age}"
        response.body_iterator = AsyncChunkIterator([body])  # type: ignore

        return response

    @staticmethod
    async def _capture_body(response: Response) -> bytes:
        chunks = []
        async for chunk in response.body_iterator:  # type: ignore
            chunks.append(chunk)
        return b"".join(chunks)
