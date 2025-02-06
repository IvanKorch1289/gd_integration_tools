from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional, Union

import aiohttp
import asyncio
import json_tricks
import time
from aiohttp import ClientTimeout, TCPConnector

from app.config.constants import RETRY_EXCEPTIONS
from app.config.settings import settings
from app.utils.decorators.singleton import singleton
from app.utils.logging_service import request_logger
from app.utils.utils import utilities


__all__ = ("HttpClient", "get_http_client")


@singleton
class HttpClient:
    """
    A singleton HTTP client with intelligent connection management.
    Maintains keep-alive connections and handles session lifecycle.
    """

    def __init__(self):
        """Initialize HTTP client with configuration from settings."""
        self.settings = settings.http_base_settings
        self.connector = self._create_connector()
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_activity: float = 0
        self.session_expiry = self.settings.keepalive_timeout + 5  # Buffer
        self.logger = request_logger

    def _create_connector(self) -> TCPConnector:
        """Create and configure TCP connector with keep-alive settings."""
        return TCPConnector(
            limit=self.settings.limit,
            limit_per_host=self.settings.limit_per_host,
            ttl_dns_cache=self.settings.ttl_dns_cache,
            ssl=False,
            force_close=False,
            keepalive_timeout=self.settings.keepalive_timeout,
        )

    async def _ensure_session(self) -> None:
        """Maintain active session with renewal based on activity."""
        now = time.monotonic()
        if self._should_renew_session(now):
            await self._close_session()
            self._create_new_session()
            self.logger.debug(
                "Created new session", extra={"session_id": id(self.session)}
            )
        self.last_activity = now

    def _should_renew_session(self, current_time: float) -> bool:
        """Determine if session needs renewal based on activity timeout."""
        return (
            self.session is None
            or self.session.closed
            or (current_time - self.last_activity) > self.session_expiry
        )

    def _create_new_session(self) -> None:
        """Initialize new client session with proper timeout settings."""
        timeout = ClientTimeout(
            total=self.settings.total_timeout,
            connect=self.settings.connect_timeout,
            sock_read=self.settings.sock_read_timeout,
        )
        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=timeout,
            auto_decompress=False,
            trust_env=True,
            connector_owner=False,
        )

    async def _close_session(self) -> None:
        """Gracefully close existing session if active."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug(
                "Closed existing session",
                extra={"session_id": id(self.session)},
            )

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
        self.logger.error("Request failed after retries", exc_info=True)
        status_code = getattr(exception, "status", None)
        headers = dict(getattr(exception, "headers", {}))

        if isinstance(exception, aiohttp.ClientResponseError):
            status_code = exception.status
            headers = dict(exception.headers)

        return {
            "status": status_code,
            "data": None,
            "headers": headers,
            "elapsed": time.monotonic() - start_time,
        }

    async def _log_request(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]],
        params: Optional[Dict[str, Any]],
        data: Optional[Union[str, bytes]],
    ) -> None:
        """Log request details with sensitive data masking."""
        safe_headers = headers.copy() if headers else {}

        # Mask authorization headers
        if "Authorization" in safe_headers:
            safe_headers["Authorization"] = "***MASKED***"

        # Truncate large data payloads
        truncated_data = ""
        if data:
            data_str = data if isinstance(data, str) else data.decode()[:200]
            truncated_data = data_str[:200] + (
                "..." if len(data_str) > 200 else ""
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

    async def _log_response(self, response: aiohttp.ClientResponse) -> None:
        """Log response details with content truncation."""
        content = ""
        try:
            content = await response.text()
            if len(content) > 500:
                content = content[:500] + "..."
        except Exception as e:
            content = f"[Unable to read response content: {str(e)}]"

        self.logger.debug(
            "Received response",
            extra={
                "status": response.status,
                "headers": dict(response.headers),
                "content": content,
            },
        )

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
        connect_timeout: Optional[float] = None,
        read_timeout: Optional[float] = None,
        total_timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Execute HTTP request with intelligent connection management.

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
            connect_timeout: Connection establishment timeout
            read_timeout: Response read timeout
            total_timeout: Total operation timeout

        Returns:
            Dictionary containing status, data, headers and timing information
        """
        start_time = time.monotonic()
        timeout = ClientTimeout(
            total=total_timeout or self.settings.total_timeout,
            connect=connect_timeout or self.settings.connect_timeout,
            sock_read=read_timeout or self.settings.sock_read_timeout,
        )

        headers = self._build_headers(auth_token, headers)
        request_data = await self._prepare_request_data(data, json)
        last_exception = None

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
                    timeout=timeout,
                ) as response:
                    await self._log_response(response)

                    if raise_for_status:
                        response.raise_for_status()

                    content = await self._process_response(
                        response, response_type
                    )
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

    async def close(self) -> None:
        """Release all network resources and connections."""
        await self._close_session()
        if not self.connector.closed:
            await self.connector.close()
            self.logger.debug("Connector closed")


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
