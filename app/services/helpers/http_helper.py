from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional, Union

import aiohttp
import asyncio
import json_tricks
from aiohttp import ClientTimeout, TCPConnector

from app.utils.logging_service import request_logger
from app.utils.utils import utilities


__all__ = ("make_request", "get_http_client")


class OptimizedClientSession:
    def __init__(self, connector: Optional[TCPConnector] = None):
        self.connector = connector or TCPConnector(
            limit=100,
            limit_per_host=20,
            ttl_dns_cache=300,
            ssl=False,
        )
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "OptimizedClientSession":
        timeout = ClientTimeout(
            total=30,
            connect=10,
            sock_read=15,
        )
        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=timeout,
            auto_decompress=False,
            trust_env=True,
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self.session:
            await self.session.close()

    async def _log_request(self, method: str, url: str, **kwargs) -> None:
        log_data = {
            "method": method,
            "url": url,
            "headers": kwargs.get("headers"),
            "params": kwargs.get("params"),
            "body_size": (
                len(kwargs.get("data", b"")) if kwargs.get("data") else 0
            ),
        }
        request_logger.info("Outgoing request", extra={"request": log_data})

    async def _log_response(self, response: aiohttp.ClientResponse) -> None:
        log_data = {
            "status": response.status,
            "headers": dict(response.headers),
            "url": str(response.url),
            "content_length": response.content_length,
        }
        request_logger.info("Received response", extra={"response": log_data})

    async def request(
        self,
        method: str,
        url: str,
        timeout: Optional[ClientTimeout] = None,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        if not self.session:
            raise RuntimeError("Session not initialized")

        await self._log_request(method, url, **kwargs)

        try:
            response = await self.session.request(
                method, url, timeout=timeout, **kwargs
            )
            await self._log_response(response)
            return response
        except aiohttp.ClientError as exc:
            request_logger.error(
                f"Request failed: {exc.__class__.__name__}", exc_info=True
            )
            raise

    async def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[ClientTimeout] = None,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        return await self.request(
            "GET", url, params=params, timeout=timeout, **kwargs
        )

    async def post(
        self,
        url: str,
        data: Optional[Union[Dict[str, Any], str, bytes]] = None,
        timeout: Optional[ClientTimeout] = None,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        return await self.request(
            "POST", url, data=data, timeout=timeout, **kwargs
        )


@asynccontextmanager
async def get_http_client() -> AsyncGenerator[OptimizedClientSession, None]:
    async with OptimizedClientSession() as client:
        yield client


async def make_request(
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
    start_time = asyncio.get_event_loop().time()

    default_headers = {
        "User-Agent": "OptimizedClient/1.0",
        "Accept-Encoding": "gzip, deflate, br",
    }
    if auth_token:
        default_headers["Authorization"] = f"Bearer {auth_token}"
    if headers:
        default_headers.update(headers)

    timeout = None
    if any([connect_timeout, read_timeout, total_timeout]):
        timeout = ClientTimeout(
            total=total_timeout,
            connect=connect_timeout,
            sock_read=read_timeout,
        )

    json_data = None
    if json is not None:
        try:
            json_data = json_tricks.dumps(
                json, extra_obj_encoders=[utilities.custom_json_encoder]
            )
        except Exception as e:
            request_logger.error(f"JSON serialization error: {e}")
            raise ValueError("Invalid JSON data") from e

    async with get_http_client() as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=default_headers,
                params=params,
                data=data if data else json_data,
                timeout=timeout,
            )

            if raise_for_status:
                response.raise_for_status()

            content = None
            if response_type == "json":
                content = await response.json()
            elif response_type == "text":
                content = await response.text()
            elif response_type == "bytes":
                content = await response.read()
            else:
                raise ValueError(f"Invalid response_type: {response_type}")

            elapsed = asyncio.get_event_loop().time() - start_time

            return {
                "status": response.status,
                "data": content,
                "headers": dict(response.headers),
                "elapsed": elapsed,
            }

        except aiohttp.ClientResponseError as e:
            request_logger.error(f"HTTP error {e.status}: {e.message}")
            if raise_for_status:
                raise
            return {
                "status": e.status,
                "data": None,
                "headers": dict(e.headers) if e.headers else {},
                "elapsed": asyncio.get_event_loop().time() - start_time,
            }
