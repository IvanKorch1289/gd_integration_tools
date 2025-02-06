from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, AsyncGenerator, Dict, Optional, Union

import aiohttp
import asyncio
import json_tricks
import time
from aiohttp import AsyncResolver, ClientTimeout, TCPConnector
from asyncio import Lock, Queue, create_task

from app.config.constants import RETRY_EXCEPTIONS
from app.config.settings import settings
from app.utils.decorators.singleton import singleton
from app.utils.logging_service import request_logger
from app.utils.utils import utilities


__all__ = ("HttpClient", "get_http_client")


class CircuitBreaker:
    """Implements circuit breaker pattern with exponential backoff."""

    def __init__(self):
        self.state = "CLOSED"
        self.failure_count = 0
        self.last_failure_time = None

    async def check_state(self, max_failures: int, reset_timeout: int) -> None:
        """Check and update circuit breaker state."""
        if (
            self.state == "OPEN"
            and datetime.now()
            > self.last_failure_time + timedelta(seconds=reset_timeout)
        ):
            self.state = "HALF-OPEN"
            self.failure_count = 0

        if self.failure_count >= max_failures:
            self.state = "OPEN"
            self.last_failure_time = datetime.now()
            raise aiohttp.ClientError("Circuit breaker tripped")

    def record_failure(self) -> None:
        """Record failed request."""
        self.failure_count += 1

    def record_success(self) -> None:
        """Reset circuit breaker on successful request."""
        if self.state == "HALF-OPEN":
            self.state = "CLOSED"
        self.failure_count = 0


@singleton
class HttpClient:
    """
    Advanced HTTP client with intelligent connection management.

    Features:
    - Safe connection pooling with keep-alive
    - Circuit breaker pattern
    - Automatic session lifecycle management
    - Retry mechanism with exponential backoff
    - Request/response logging with sensitive data masking
    - Performance metrics collection
    - Background connection purging
    - DNS caching
    """

    def __init__(self):
        """Initialize HTTP client with configuration from settings."""
        self.settings = settings.http_base_settings
        self.connector: Optional[TCPConnector] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_activity: float = 0
        self.active_requests: int = 0
        self.session_lock = Lock()
        self.logger = request_logger
        self.circuit_breaker = CircuitBreaker()
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0,
        }
        self._init_purging()

    # region Session Management
    async def _ensure_session(self) -> None:
        """Maintain active session with renewal based on activity."""
        async with self.session_lock:
            now = time.monotonic()
            if self._should_renew_session(now):
                await self._close_session()
                self._create_new_session()
                self.logger.debug(
                    "Created new session",
                    extra={"session_id": id(self.session)},
                )
            self.last_activity = now

    def _should_renew_session(self, current_time: float) -> bool:
        """Determine if session needs renewal based on activity timeout."""
        session_expiry = self.settings.keepalive_timeout + 5
        return (
            self.session is None
            or self.session.closed
            or (
                current_time - self.last_activity > session_expiry
                and self.active_requests == 0
            )
        )

    def _create_new_session(self) -> None:
        """Initialize new client session with proper timeout settings."""
        self.connector = TCPConnector(
            limit=self.settings.limit,
            limit_per_host=self.settings.limit_per_host,
            ttl_dns_cache=self.settings.ttl_dns_cache,
            ssl=self.settings.ssl_verify,
            force_close=self.settings.force_close,
            keepalive_timeout=self.settings.keepalive_timeout,
            resolver=AsyncResolver(),
        )

        timeout = ClientTimeout(
            total=self.settings.total_timeout,
            connect=self.settings.connect_timeout,
            sock_read=self.settings.sock_read_timeout,
        )

        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=timeout,
            auto_decompress=True,
            trust_env=True,
            connector_owner=False,
        )

    async def _close_session(self) -> None:
        """Gracefully close existing session if active."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug(
                "Closed session", extra={"session_id": id(self.session)}
            )
            self.session = None

    # endregion

    # region Request Processing
    async def make_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Union[Dict[str, Any], str, bytes]] = None,
        auth_token: Optional[str] = None,
        response_type: str = "json",
        raise_for_status: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute HTTP request with full error handling and retry logic.

        Args:
            method: HTTP verb (GET, POST, etc.)
            url: Target URL for the request
            headers: Optional custom headers
            json: JSON-serializable request body
            params: URL query parameters
            data: Raw request body data
            auth_token: Bearer token for authorization
            response_type: Expected response format (json/text/bytes)
            raise_for_status: Raise exception for HTTP errors

        Returns:
            Dictionary containing status, data, headers and timing information
        """
        start_time = time.monotonic()
        last_exception = None
        request_data = await self._prepare_request_data(data, json)
        headers = self._build_headers(auth_token, headers)

        try:
            await self.circuit_breaker.check_state(
                self.settings.circuit_breaker_max_failures,
                self.settings.circuit_breaker_reset_timeout,
            )

            for attempt in range(self.settings.max_retries + 1):
                try:
                    await self._ensure_session()
                    await self._log_request(
                        method, url, headers, params, request_data
                    )

                    async with self.session.request(
                        method=method,
                        url=url,
                        headers=headers,
                        params=params,
                        data=request_data,
                    ) as response:
                        content = await self._process_response(
                            response, response_type
                        )
                        await self._log_response(response, content)

                        if raise_for_status:
                            response.raise_for_status()

                        return self._build_response_object(
                            response, content, start_time
                        )

                except (aiohttp.ClientResponseError, *RETRY_EXCEPTIONS) as exc:
                    last_exception = exc
                    if not self._should_retry(attempt, exc):
                        break
                    await self._handle_retry(attempt)

            if raise_for_status and last_exception:
                raise last_exception

            return self._handle_final_error(last_exception, start_time)

        finally:
            self._update_metrics(start_time, success=last_exception is None)
            self.last_activity = time.monotonic()

    # endregion

    # region Helpers
    def _build_headers(
        self,
        auth_token: Optional[str],
        custom_headers: Optional[Dict[str, str]],
    ) -> Dict[str, str]:
        """Construct headers with authentication and custom values."""
        headers = {
            "User-Agent": "HttpClient/1.0",
            "Accept-Encoding": "gzip, deflate, br",
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if custom_headers:
            headers.update(custom_headers)
        return headers

    async def _prepare_request_data(
        self,
        data: Optional[Union[Dict[str, Any], str, bytes]],
        json_data: Optional[Dict[str, Any]],
    ) -> Optional[Union[str, bytes]]:
        """Serialize JSON data and validate request payload."""
        if json_data is not None:
            try:
                return json_tricks.dumps(
                    json_data,
                    extra_obj_encoders=[utilities.custom_json_encoder],
                )
            except Exception as exc:
                self.logger.error("JSON serialization error", exc_info=True)
                raise ValueError("Invalid JSON data") from exc
        return data

    def _should_retry(self, attempt: int, exception: Exception) -> bool:
        """Determine if a request should be retried."""
        if attempt >= self.settings.max_retries:
            return False
        if isinstance(exception, aiohttp.ClientResponseError):
            return exception.status in self.settings.retry_status_codes
        return isinstance(exception, RETRY_EXCEPTIONS)

    async def _handle_retry(self, attempt: int) -> None:
        """Perform retry delay with exponential backoff."""
        sleep_time = self.settings.retry_backoff_factor * (2**attempt)
        await asyncio.sleep(sleep_time)

    # endregion

    # region Logging & Metrics
    async def _log_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        params: Dict[str, Any],
        data: Optional[Union[str, bytes]],
    ) -> None:
        """Log request details with sensitive data masking."""
        safe_headers = {
            k: "***MASKED***" if k.lower() == "authorization" else v
            for k, v in headers.items()
        }
        truncated_data = (
            str(data)[:200] + "..." if data and len(str(data)) > 200 else data
        )

        self.logger.debug(
            "Making request",
            extra={
                "method": method,
                "url": url,
                "headers": safe_headers,
                "params": params,
                "data": truncated_data,
            },
        )

    async def _log_response(
        self, response: aiohttp.ClientResponse, content: Any
    ) -> None:
        """Log response details with content truncation."""
        self.logger.debug(
            "Received response",
            extra={
                "status": response.status,
                "headers": dict(response.headers),
                "content": (
                    str(content)[:500] + "..."
                    if len(str(content)) > 500
                    else content
                ),
            },
        )

    def _update_metrics(self, start_time: float, success: bool) -> None:
        """Update performance metrics."""
        duration = time.monotonic() - start_time
        self.metrics["total_requests"] += 1
        key = "successful_requests" if success else "failed_requests"
        self.metrics[key] += 1
        self.metrics["average_response_time"] = (
            0.9 * self.metrics["average_response_time"] + 0.1 * duration
        )

    # endregion

    # region Response Handling
    def _build_response_object(
        self, response: aiohttp.ClientResponse, content: Any, start_time: float
    ) -> Dict[str, Any]:
        """Construct standardized response dictionary."""
        return {
            "status": response.status,
            "data": content,
            "headers": dict(response.headers),
            "elapsed": time.monotonic() - start_time,
        }

    def _handle_final_error(
        self, exception: Optional[Exception], start_time: float
    ) -> Dict[str, Any]:
        """Create error response after exhausting retries."""
        status_code = getattr(exception, "status", None)
        headers = dict(getattr(exception, "headers", {}))

        return {
            "status": status_code,
            "data": None,
            "headers": headers,
            "elapsed": time.monotonic() - start_time,
        }

    async def _process_response(
        self, response: aiohttp.ClientResponse, response_type: str
    ) -> Any:
        """Process response content according to specified type."""
        content = await response.read()

        if response_type == "json":
            try:
                return json_tricks.loads(content)
            except Exception as e:
                self.logger.error(
                    "JSON parsing error",
                    extra={"content": content[:200], "error": str(e)},
                )
                raise ValueError("Invalid JSON response") from e
        if response_type == "text":
            return content.decode(errors="replace")
        if response_type == "bytes":
            return content
        raise ValueError(f"Unsupported response type: {response_type}")

    # endregion

    # region Connection Management
    def _init_purging(self) -> None:
        """Initialize background connection purging task."""
        self.purging_queue = Queue()
        create_task(self._connection_purger())

    async def _connection_purger(self) -> None:
        """Background task to purge idle connections."""
        while True:
            await asyncio.sleep(self.settings.purging_interval)
            if self.connector and self.settings.enable_connection_purging:
                await self.connector._purge_loose()

    async def close(self) -> None:
        """Release all network resources and connections."""
        async with self.session_lock:
            await self._close_session()
            if self.connector and not self.connector.closed:
                await self.connector.close()

    # endregion


@asynccontextmanager
async def get_http_client() -> AsyncGenerator[HttpClient, None]:
    """
    Context manager for HTTP client with connection pooling.

    Yields:
        Configured HttpClient instance
    """
    client = HttpClient()
    try:
        yield client
    finally:
        await client.close()
