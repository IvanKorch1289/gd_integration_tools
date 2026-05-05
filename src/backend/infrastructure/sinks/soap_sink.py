"""SoapSink — outbound SOAP/WSDL call через ``zeep`` (Wave 3.1).

``zeep`` — sync-only клиент; обёртка через ``asyncio.to_thread``.
Lazy-импорт. WSDL загружается лениво при первом вызове, кэшируется
на инстанс.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from src.core.interfaces.sink import Sink, SinkKind, SinkResult

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
    timeout: float = 30.0
    kind: SinkKind = field(default=SinkKind.SOAP, init=False)
    _client: Any = field(default=None, init=False, repr=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )

    async def send(self, payload: Any) -> SinkResult:
        """Вызывает SOAP-операцию через ``asyncio.to_thread`` (zeep — sync)."""
        try:
            client = await asyncio.to_thread(self._get_client)
        except Exception as exc:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )

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

    async def health(self) -> bool:
        """Health: успешная загрузка WSDL."""
        try:
            client = await asyncio.to_thread(self._get_client)
        except Exception:  # noqa: BLE001
            return False
        return client is not None


def _summarize(result: Any) -> str:
    """Сжимает SOAP-ответ до короткой строки для ``SinkResult.details``."""
    text = repr(result)
    return text if len(text) < 256 else text[:253] + "..."
