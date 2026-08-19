"""SoapSink — outbound SOAP/WSDL call через ``zeep`` (Wave 3.1).

``zeep`` — sync-only клиент; обёртка через ``asyncio.to_thread``.
Lazy-импорт. WSDL загружается лениво при первом вызове, кэшируется
на инстанс.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.logging import get_logger
from src.backend.core.resilience.connector_breaker import with_breaker
from src.backend.core.resilience.retry import with_retry
from src.backend.core.security.connector_auth import require_capability
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.sinks._timeouts import SOAP_SINK_TIMEOUT_S

_logger = get_logger(__name__)

__all__ = ("SoapSink",)


@dataclass(slots=True)
class SoapSink(Sink):
    """SOAP/WSDL sink — вызывает указанную операцию.

    Args:
        sink_id: Уникальный идентификатор.
        wsdl_url: URL/path к WSDL.
        operation: Имя SOAP-операции.
        service_name: Имя сервиса в WSDL (опционально).
        port_name: Имя port (опционально).
        timeout: Таймаут в секундах.

    ``payload`` — dict с именованными параметрами SOAP-операции.

    """

    sink_id: str
    wsdl_url: str
    operation: str
    service_name: str | None = None
    port_name: str | None = None
    timeout: float = SOAP_SINK_TIMEOUT_S  # Cycle 12: externalized to sinks/_timeouts
    kind: SinkKind = field(default=SinkKind.SOAP, init=False)
    _client: Any = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    @with_breaker("soap_sink")
    @with_retry(max_attempts=3, retry_on=(ConnectionError, TimeoutError, OSError))
    @require_capability("soap.invoke", action="write")
    async def send(self, payload: Any) -> SinkResult:
        """Вызывает SOAP-операцию через ``asyncio.to_thread`` (zeep — sync)."""
        try:
            client = await asyncio.to_thread(self._get_client)
        except Exception as exc:
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )
        if client is None:
            return SinkResult(ok=False, details={"error": "zeep not installed"})

        kwargs: dict[str, Any] = (
            payload if isinstance(payload, dict) else {"body": payload}
        )

        try:
            result = await asyncio.to_thread(self._invoke_sync, client, kwargs)
        except Exception:
            # Cycle 22 P1-6: re-raise transport exception so
            # @with_retry / @with_breaker decorators can see it.
            raise

        return SinkResult(
            ok=True,
            details={"operation": self.operation, "response": _summarize(result)},
        )

    def _get_client(self) -> Any:
        """Возвращает кэшированный ``zeep.Client``; загружает WSDL при первом вызове."""
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                from zeep import Client
                from zeep.transports import Transport
            except ImportError:
                return None
            transport = Transport(timeout=self.timeout)
            # Cycle 20 P0-7: WSDL SSRF surface. Allow only http(s) URLs;
            # file:// and other schemes are denied to prevent reading
            # local files or reaching internal-network endpoints.
            from urllib.parse import urlparse

            parsed = urlparse(self.wsdl_url)
            if parsed.scheme not in ("http", "https"):
                _logger.error(
                    "SOAP sink WSDL denied: scheme %r not in (http, https); "
                    "wsdl_url=%s",
                    parsed.scheme,
                    self.wsdl_url,
                )
                return None
            self._client = Client(self.wsdl_url, transport=transport)
            return self._client

    def _invoke_sync(self, client: Any, kwargs: dict[str, Any]) -> Any:
        """Синхронный вызов SOAP-операции (через ``ServiceProxy``)."""
        if self.service_name and self.port_name:
            service = client.bind(self.service_name, self.port_name)
        else:
            service = client.service
        method = getattr(service, self.operation)
        return method(**kwargs)

    async def health(self, mode: str = "fast") -> HealthResult:
        """Health: успешная загрузка WSDL."""
        start = time.perf_counter()
        try:
            client = await asyncio.to_thread(self._get_client)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
        latency_ms = (time.perf_counter() - start) * 1000.0
        if client is not None:
            return HealthResult.ok(latency_ms=latency_ms, mode=mode)
        return HealthResult.failed(
            error="zeep not installed", mode=mode, latency_ms=latency_ms
        )


def _summarize(result: Any) -> str:
    """Сжимает SOAP-ответ до короткой строки для ``SinkResult.details``."""
    text = repr(result)
    return text if len(text) < 256 else text[:253] + "..."
