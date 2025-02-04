import re
import uuid
from typing import List, Pattern

import asyncio
import time
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.types import ASGIApp

from app.config.settings import settings
from app.utils.logging_service import app_logger


__all__ = (
    "InnerRequestLoggingMiddleware",
    "APIKeyMiddleware",
    "TimeoutMiddleware",
    "RequestIDMiddleware",
    "SecurityHeadersMiddleware",
)


class InnerRequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging incoming requests and outgoing responses"""

    def __init__(
        self, app: ASGIApp, log_body: bool = True, max_body_size: int = 4096
    ):
        super().__init__(app)
        self.log_body = log_body
        self.max_body_size = max_body_size

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process and log request/response information"""
        app_logger.info(f"Request: {request.method} {request.url}")

        start_time = time.time()

        if self.log_body and request.method == "POST":
            content_type = request.headers.get("Content-Type", "").lower()
            if "multipart/form-data" not in content_type:
                await self._get_request_body(request)

        try:
            response = await call_next(request)
        except Exception as exc:
            app_logger.error(f"Request processing error: {exc}", exc_info=True)
            raise

        if self.log_body:
            await self._log_response_body(response)

        process_time = (time.time() - start_time) * 1000
        app_logger.info(
            f"Response: {response.status_code} | {request.method} {request.url.path} "
            f"processed in {process_time:.2f} ms"
        )

        return response

    async def _get_request_body(self, request: Request) -> bytes:
        """Retrieve and log request body with size limit"""
        try:
            body = await request.body()
            if len(body) > self.max_body_size:
                return b"<body too large to log>"

            app_logger.debug(f"Request body: {body.decode('utf-8')}")
            return body
        except UnicodeDecodeError:
            app_logger.warning(
                "Request body contains binary data, skipping logging"
            )
            return b""

    async def _log_response_body(self, response: Response) -> None:
        """Log response body with size limit"""
        content_type = response.headers.get("Content-Type", "").lower()
        if "text" in content_type or "json" in content_type:
            body = await self._capture_response_body(response)
            if len(body) > self.max_body_size:
                app_logger.debug("Response body too large to log")
            else:
                app_logger.debug(f"Response body: {body.decode('utf-8')}")

    @staticmethod
    async def _capture_response_body(response: Response) -> bytes:
        """Capture response body while maintaining the original iterator"""
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        response.body_iterator = AsyncChunkIterator(chunks)
        return b"".join(chunks)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware for API key validation in request headers"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.compiled_patterns: List[Pattern] = [
            re.compile(self._convert_pattern(pattern))
            for pattern in settings.auth.routes_without_api_key
        ]

    @staticmethod
    def _convert_pattern(pattern: str) -> str:
        """Convert route pattern to regex pattern"""
        return f"^{pattern.replace('*', '.*')}$"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if self._is_excluded_route(request.url.path):
            return await call_next(request)

        if (api_key := request.headers.get("X-API-Key")) is None:
            raise HTTPException(status_code=401, detail="API key required")

        if api_key != settings.auth.api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

        return await call_next(request)

    def _is_excluded_route(self, path: str) -> bool:
        """Check if route is excluded from API key validation"""
        return any(pattern.match(path) for pattern in self.compiled_patterns)


class TimeoutMiddleware(BaseHTTPMiddleware):
    """Middleware for request processing timeout"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        try:
            return await asyncio.wait_for(
                call_next(request), timeout=settings.auth.auth_request_timeout
            )
        except asyncio.TimeoutError:
            app_logger.warning(f"Request timeout: {request.url}")
            return JSONResponse(
                {"detail": "Request processing timeout"}, status_code=408
            )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware for adding security headers to responses"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
            }
        )
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware for adding unique request ID to each request"""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or self._generate_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _generate_id() -> str:
        return uuid.uuid4().hex


class AsyncChunkIterator:
    """Async iterator for sequential traversal of byte chunks"""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            result = self.chunks[self.index]
            self.index += 1
            return result
        except IndexError:
            raise StopAsyncIteration
