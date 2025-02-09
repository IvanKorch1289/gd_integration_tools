import time
from fastapi import Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.types import ASGIApp

from app.utils.logging_service import app_logger
from app.utils.utils import AsyncChunkIterator


__all__ = ("InnerRequestLoggingMiddleware",)


class InnerRequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging incoming requests and outgoing responses"""

    def __init__(
        self, app: ASGIApp, log_body: bool = True, max_body_size: int = 4096
    ):
        super().__init__(app)
        self.log_body = log_body
        self.max_body_size = max_body_size
        self.logger = app_logger

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process and log request/response information"""
        self.logger.info(f"Request: {request.method} {request.url}")

        start_time = time.time()

        if self.log_body and request.method == "POST":
            content_type = request.headers.get("Content-Type", "").lower()
            if "multipart/form-data" not in content_type:
                await self._get_request_body(request)

        try:
            response = await call_next(request)
        except Exception:
            self.logger.error("Request processing error", exc_info=True)
            raise

        if self.log_body:
            await self._log_response_body(response)

        process_time = (time.time() - start_time) * 1000
        self.logger.info(
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

            self.logger.debug(f"Request body: {body.decode('utf-8')}")
            return body
        except UnicodeDecodeError:
            self.logger.warning(
                "Request body contains binary data, skipping logging"
            )
            return b""

    async def _log_response_body(self, response: Response) -> None:
        """Log response body with size limit"""
        content_type = response.headers.get("Content-Type", "").lower()
        if "text" in content_type or "json" in content_type:
            body = await self._capture_response_body(response)
            if len(body) > self.max_body_size:
                self.logger.debug("Response body too large to log")
            else:
                self.logger.debug(f"Response body: {body.decode('utf-8')}")

    @staticmethod
    async def _capture_response_body(response: Response) -> bytes:
        """Capture response body while maintaining the original iterator"""
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        response.body_iterator = AsyncChunkIterator(chunks)
        return b"".join(chunks)
