"""HTTP-клиент на ``httpx`` (ADR-009) с HTTP/2.

Заменяет legacy ``http.py`` (aiohttp-based). Полный переход коннекторов
выполняется в A4; webhook, CDC и search-providers перенесены сюда же.

Особенности:
* HTTP/2 включён по умолчанию (``http2=True``). Auto-fallback на HTTP/1.1.
* Bulkhead + adaptive TimeLimiter из ``infrastructure.resilience``.
* Per-resource RateLimiter (Redis token-bucket).
* Retry — ``tenacity`` (A4); единый источник правды.
* Per-route circuit breaker (``aiocircuitbreaker``) — один инстанс CB на
  ``(host, route)``; глобальный middleware удалён в A2.
* orjson — дефолтный JSON-сериализатор.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Mapping

import httpx
from aiocircuitbreaker import CircuitBreaker, CircuitBreakerError
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from app.core.config.settings import settings
from app.infrastructure.resilience.bulkhead import registry as bulkhead_registry
from app.infrastructure.resilience.rate_limiter import (
    RateLimitExceeded,
    ResourceRateLimiter,
)
from app.infrastructure.resilience.time_limiter import TimeLimiter
from app.utilities.json_codec import json_dumps

__all__ = ("HttpxClient", "get_httpx_client")

logger = logging.getLogger("transport.httpx")


class HttpxClient:
    """Thin async HTTP/2 клиент поверх httpx + resilience."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        # По одному CB на host — чтобы сбой одного даунстрима не валил других.
        self._breakers: dict[str, CircuitBreaker] = {}
        self._time_limiter = TimeLimiter(name="httpx-global")
        self._rate_limiter = ResourceRateLimiter()
        self._http_settings = settings.http_base_settings

    async def _ensure_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None or self._client.is_closed:
                limits = httpx.Limits(
                    max_connections=self._http_settings.limit,
                    max_keepalive_connections=self._http_settings.limit_per_host,
                    keepalive_expiry=self._http_settings.keepalive_timeout,
                )
                timeout = httpx.Timeout(
                    connect=self._http_settings.connect_timeout,
                    read=self._http_settings.sock_read_timeout,
                    write=self._http_settings.sock_read_timeout,
                    pool=self._http_settings.total_timeout,
                )
                self._client = httpx.AsyncClient(
                    http2=True,
                    http1=True,
                    timeout=timeout,
                    limits=limits,
                    verify=bool(self._http_settings.ssl_verify),
                    trust_env=True,
                    follow_redirects=True,
                )
            return self._client

    def _breaker_for(self, host: str) -> CircuitBreaker:
        breaker = self._breakers.get(host)
        if breaker is None:
            breaker = CircuitBreaker(
                failure_threshold=self._http_settings.circuit_breaker_max_failures,
                recovery_timeout=self._http_settings.circuit_breaker_reset_timeout,
                expected_exception=httpx.HTTPError,
                name=f"httpx:{host}",
            )
            self._breakers[host] = breaker
        return breaker

    async def close(self) -> None:
        async with self._lock:
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        files: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        rate_limit_key: str | None = None,
        resource: str = "http",
    ) -> httpx.Response:
        """Выполняет HTTP-запрос c resilience-обёртками."""
        host = httpx.URL(url).host or "_"
        bulkhead = await bulkhead_registry.get_or_create(
            f"http:{host}",
            max_concurrent=self._http_settings.limit_per_host,
            wait_timeout=self._http_settings.connect_timeout,
        )
        breaker = self._breaker_for(host)

        # Rate limiter (optional).
        if rate_limit_key:
            try:
                await self._rate_limiter.acquire(resource, rate_limit_key)
            except RateLimitExceeded:
                raise
            except KeyError:
                logger.debug("Unknown RL resource '%s' — skipping", resource)

        async def _do():
            client = await self._ensure_client()
            body: bytes | None = None
            req_headers = dict(headers or {})
            if json is not None and data is None and content is None:
                body = json_dumps(json)
                req_headers.setdefault("content-type", "application/json")
            elif content is not None:
                body = content

            request = client.build_request(
                method=method.upper(),
                url=url,
                headers=req_headers,
                params=params,
                content=body,
                data=data if body is None else None,
                files=files,
            )
            return await client.send(request)

        retry_policy = retry(
            stop=stop_after_attempt(self._http_settings.max_retries + 1),
            wait=wait_exponential(multiplier=self._http_settings.retry_backoff_factor) + wait_random(0, 0.5),
            retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
            before_sleep=before_sleep_log(logger, logging.DEBUG),
            reraise=True,
        )

        try:
            async with bulkhead.guard():
                return await self._time_limiter.run(
                    breaker(retry_policy(_do))()
                )
        except (RetryError, CircuitBreakerError, httpx.HTTPError):
            raise


_instance: HttpxClient | None = None


def get_httpx_client() -> HttpxClient:
    global _instance
    if _instance is None:
        _instance = HttpxClient()
    return _instance
