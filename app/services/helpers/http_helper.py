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


__all__ = (
    "HttpClient",
    "get_http_client",
)


@singleton
class HttpClient:
    """
    A singleton HTTP client for making optimized and reusable HTTP requests.
    Handles connection pooling, retries, timeouts, and logging.
    """

    def __init__(self):
        """Initialize the HTTP client with connection pooling and default settings."""
        self.settings = settings.http_base_settings
        self.connector = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_used: float = 0
        self.logger = request_logger
        self._init_connector()

    def _init_connector(self):
        """Initialize the connector"""
        self.connector = TCPConnector(
            limit=self.settings.limit,
            limit_per_host=self.settings.limit_per_host,
            ttl_dns_cache=self.settings.ttl_dns_cache,
            ssl=False,
            force_close=self.settings.force_close,  # Важно для повторного использования соединений
            keepalive_timeout=self.settings.keepalive_timeout,
        )

    async def _should_recreate_session(self) -> bool:
        """Checking recreate session neeeded"""
        if self.session is None or self.session.closed:
            return True

        # Проверка таймаута бездействия
        idle_time = time.monotonic() - self.last_used
        if idle_time > self.settings.keepalive_timeout:
            self.logger.debug(f"Session expired after {idle_time:.2f}s idle")
            return True

        return False

    async def _ensure_session(self):
        """Ensure the aiohttp session is created and ready for use."""
        if await self._should_recreate_session():
            await self.close()  # Закрываем старую сессию перед созданием новой

            timeout = ClientTimeout(
                total=self.settings.total_timeout,
                connect=self.settings.connect_timeout,
                sock_read=self.settings.sock_read_timeout,
            )

            self.session = aiohttp.ClientSession(
                connector=self.connector,
                timeout=timeout,
                connector_keepalive_timeout=self.settings.keepalive_timeout,  # Исправленный параметр
                auto_decompress=False,
                trust_env=True,
                connector_owner=False,
            )
            self.last_used = time.monotonic()
            self.logger.debug("Created new session")

    async def _log_request(self, method: str, url: str, **kwargs) -> None:
        """Log outgoing HTTP requests."""
        log_data = {
            "method": method,
            "url": url,
            "headers": kwargs.get("headers"),
            "params": kwargs.get("params"),
            "body_size": (
                len(kwargs.get("data", b"")) if kwargs.get("data") else 0
            ),
        }
        self.logger.info("Outgoing request", extra={"request": log_data})

    async def _log_response(self, response: aiohttp.ClientResponse) -> None:
        """Log incoming HTTP responses."""
        log_data = {
            "status": response.status,
            "headers": dict(response.headers),
            "url": str(response.url),
            "content_length": response.content_length,
        }
        self.logger.info("Received response", extra={"response": log_data})

    async def _process_response(
        self, response: aiohttp.ClientResponse, response_type: str
    ) -> Any:
        """Process the response based on the specified response type."""
        if response_type == "json":
            return await response.json()
        if response_type == "text":
            return await response.text()
        if response_type == "bytes":
            return await response.read()
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
        Make an HTTP request with retries, connection pooling, and logging.

        Args:
            method: HTTP method (GET, POST, etc.).
            url: Target URL.
            headers: Additional headers.
            json: JSON data to send.
            params: URL parameters.
            data: Raw data to send.
            auth_token: Authorization token.
            response_type: Type of response data (json, text, bytes).
            raise_for_status: Raise an exception for HTTP errors.
            connect_timeout: Connection timeout.
            read_timeout: Read timeout.
            total_timeout: Total request timeout.

        Returns:
            A dictionary containing the response status, data, headers, and elapsed time.
        """
        start_time = time.monotonic()
        timeout = ClientTimeout(
            total=total_timeout,
            connect=connect_timeout,
            sock_read=read_timeout,
        )

        default_headers = {
            "User-Agent": "HttpClient/1.0",
            "Accept-Encoding": "gzip, deflate, br",
        }

        if auth_token:
            default_headers["Authorization"] = f"Bearer {auth_token}"
        if headers:
            default_headers.update(headers)

        json_data = None

        if json is not None:
            try:
                json_data = json_tricks.dumps(
                    json, extra_obj_encoders=[utilities.custom_json_encoder]
                )
            except Exception as exc:
                self.logger.error("JSON serialization error", exc_info=True)
                raise ValueError("Invalid JSON data") from exc

        last_exception = None

        for attempt in range(self.settings.max_retries + 1):
            try:
                await self._ensure_session()
                await self._log_request(
                    method,
                    url,
                    headers=default_headers,
                    params=params,
                    data=data or json_data,
                )

                response = await self.session.request(
                    method=method,
                    url=url,
                    headers=default_headers,
                    params=params,
                    data=data if data else json_data,
                    timeout=timeout,
                )
                await self._log_response(response)

                if raise_for_status:
                    response.raise_for_status()

                content = await self._process_response(response, response_type)
                elapsed = time.monotonic() - start_time

                return {
                    "status": response.status,
                    "data": content,
                    "headers": dict(response.headers),
                    "elapsed": elapsed,
                }

            except (aiohttp.ClientResponseError, *RETRY_EXCEPTIONS) as exc:
                last_exception = exc
                if (
                    attempt == self.settings.max_retries
                    or not isinstance(exc, aiohttp.ClientResponseError)
                    or exc.status not in self.settings.retry_status_codes
                ):
                    break
                sleep_time = self.settings.retry_backoff_factor * (2**attempt)
                await asyncio.sleep(sleep_time)

        self.logger.error("Request failed after retries", exc_info=True)
        if raise_for_status and last_exception:
            raise last_exception
        return {
            "status": getattr(last_exception, "status", None),
            "data": None,
            "headers": dict(getattr(last_exception, "headers", {})),
            "elapsed": time.monotonic() - start_time,
        }

    async def close(self):
        """Close the HTTP session and release resources."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.logger.debug("Session closed")
        if self.connector and not self.connector.closed:
            await self.connector.close()
            self.logger.debug("Connector closed")
        self.session = None
        self.connector = None


@asynccontextmanager
async def get_http_client() -> AsyncGenerator[HttpClient, None]:
    """
    Context manager for using the HttpClient.
    Ensures the session is reused and not closed prematurely.
    """
    client = HttpClient()
    try:
        yield client
    finally:
        pass
