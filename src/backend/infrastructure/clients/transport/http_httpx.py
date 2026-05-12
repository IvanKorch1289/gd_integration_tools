"""HTTP-клиент на ``httpx`` (ADR-009) с HTTP/2.

Заменяет legacy ``http.py`` (aiohttp-based). Полный переход коннекторов
выполняется в A4; webhook, CDC и search-providers перенесены сюда же.

Особенности:
* HTTP/2 включён по умолчанию (``http2=True``). Auto-fallback на HTTP/1.1.
* Bulkhead + adaptive TimeLimiter из ``infrastructure.resilience``.
* Per-resource RateLimiter (Redis token-bucket).
* Retry — ``tenacity``; единый источник правды.
* Per-host circuit breaker — единый фасад
  ``infrastructure.resilience.breaker.BreakerRegistry`` (purgatory backend, Wave 6.1).
* orjson — дефолтный JSON-сериализатор.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

import httpx
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from src.backend.core.config.settings import settings
from src.backend.core.resilience.breaker import (
    Breaker,
    BreakerSpec,
    CircuitOpen,
    get_breaker_registry,
)
from src.backend.dsl.codec.json import json_dumps
from src.backend.infrastructure.resilience.bulkhead import registry as bulkhead_registry
from src.backend.infrastructure.resilience.rate_limiter import (
    RateLimitExceeded,
    ResourceRateLimiter,
)
from src.backend.infrastructure.resilience.time_limiter import TimeLimiter

breaker_registry = get_breaker_registry()

__all__ = ("HttpxClient", "get_httpx_client")

logger = logging.getLogger("transport.httpx")


class HttpxClient:
    """Thin async HTTP/2 клиент поверх httpx + resilience."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._time_limiter = TimeLimiter(name="httpx-global")
        self._rate_limiter = ResourceRateLimiter()
        self._http_settings = settings.http_base_settings
        self._cert_subscribed: bool = False

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
                cert = self._build_cert_tuple()
                kwargs: dict[str, Any] = {
                    "http2": True,
                    "http1": True,
                    "timeout": timeout,
                    "limits": limits,
                    "verify": bool(self._http_settings.ssl_verify),
                    "trust_env": True,
                    "follow_redirects": True,
                }
                if cert is not None:
                    kwargs["cert"] = cert
                self._client = httpx.AsyncClient(**kwargs)
                self._maybe_subscribe_rotation()
            return self._client

    def _build_cert_tuple(
        self,
    ) -> tuple[str, str] | tuple[str, str, str] | None:
        """Собирает ``cert`` для ``httpx.AsyncClient`` или ``None`` (no-op)."""
        cert_path = self._http_settings.client_cert_path
        key_path = self._http_settings.client_key_path
        if cert_path is None or key_path is None:
            return None
        password = self._http_settings.client_cert_password
        if password is not None:
            return (str(cert_path), str(key_path), password.get_secret_value())
        return (str(cert_path), str(key_path))

    def _maybe_subscribe_rotation(self) -> None:
        """Подписаться на ``CertStore.on_rotation`` если он зарегистрирован.

        Идемпотентно — повторная подписка пропускается. На событии ротации
        под локом закрываем старый ``AsyncClient`` и сбрасываем self._client,
        чтобы следующий ``_ensure_client`` пересоздал его с новым cert.
        """
        if self._cert_subscribed:
            return
        cert_path = self._http_settings.client_cert_path
        if cert_path is None:
            return
        try:
            from src.backend.core.svcs_registry import get_service, has_service
            from src.backend.infrastructure.security.cert_store import CertStore
        except Exception:  # noqa: BLE001
            return
        if not has_service(CertStore):
            return
        try:
            cert_store = get_service(CertStore)
        except Exception:  # noqa: BLE001
            return
        # CertStore API имеет несколько форм (project-зависимо):
        # — `on_rotation(path, callback)` (план);
        # — `register_listener(callback)` (текущая реализация);
        # выбираем по факту наличия.
        on_rotation = getattr(cert_store, "on_rotation", None)
        if callable(on_rotation):
            try:
                on_rotation(str(cert_path), self._on_cert_rotated)
                self._cert_subscribed = True
                return
            except Exception:  # noqa: BLE001
                pass
        register_listener = getattr(cert_store, "register_listener", None)
        if callable(register_listener):
            try:
                register_listener(self._on_cert_rotated)
                self._cert_subscribed = True
            except Exception:  # noqa: BLE001
                return

    def _on_cert_rotated(self, *_args: Any, **_kwargs: Any) -> None:
        """Callback ротации: закрыть старый client (next _ensure_client пересоздаст)."""
        client = self._client
        self._client = None
        if client is None or client.is_closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(client.aclose())

    def _breaker_for(self, host: str) -> Breaker:
        return breaker_registry.get_or_create(
            f"httpx:{host}",
            BreakerSpec(
                failure_threshold=self._http_settings.circuit_breaker_max_failures,
                recovery_timeout=self._http_settings.circuit_breaker_reset_timeout,
            ),
            host=host,
        )

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
            wait=wait_exponential(multiplier=self._http_settings.retry_backoff_factor)
            + wait_random(0, 0.5),
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.TimeoutException)
            ),
            before_sleep=before_sleep_log(logger, logging.DEBUG),
            reraise=True,
        )

        async def _do_with_cb() -> httpx.Response:
            async with breaker.guard():
                return await retry_policy(_do)()

        try:
            async with bulkhead.guard():
                return await self._time_limiter.run(_do_with_cb())
        except RetryError, CircuitOpen, httpx.HTTPError:
            raise


_instance: HttpxClient | None = None


def get_httpx_client() -> HttpxClient:
    global _instance
    if _instance is None:
        _instance = HttpxClient()
    return _instance
