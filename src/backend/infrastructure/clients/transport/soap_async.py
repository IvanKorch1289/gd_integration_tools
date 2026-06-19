"""Async SOAP-клиент на httpx + lxml (C11, ADR-009).

Альтернатива zeep (sync, deprecated). Для простых SOAP-вызовов
(одиночный POST XML envelope без сложных WSDL-инклюдов) этого
достаточно; для продвинутых сценариев — `aiohttp-soap` (включено в
extras гуманитарно).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# NB: порядок импортов критичен (S163 W3 lesson, см. ftp.py).
# ``core.config.settings`` грузится ПЕРВЫМ — pre-breaks circular import chain
# breaker → core.logging → infrastructure.logging → core.interfaces → breaker.
from src.backend.core.config.settings import settings as _settings  # noqa: F401
from src.backend.core.resilience.breaker import (
    BreakerSpec,
    get_breaker_registry,
)
from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("AsyncSoapClient",)

logger = get_logger("transport.soap_async")

# S163 W4: единый canonical breaker для всех SOAP-вызовов (per endpoint можно
# расширить позже через Settings.endpoint). Pattern matching smtp.py:68-75.
_SOAP_BREAKER = get_breaker_registry().get_or_create(
    "soap_async",
    BreakerSpec(name="soap_async", failure_threshold=5, recovery_timeout=60.0),
)

# S163 W10: retry для call(). Pattern из smtp.py:233-241 + ftp.py W8.
# Retry при httpx/сетевых ошибках + TimeoutError. 3 попытки, exponential backoff.
try:
    from src.backend.infrastructure.resilience.retry import make_async_retry
except ImportError:  # pragma: no cover
    make_async_retry = None  # type: ignore[assignment]

_soap_retry = (
    make_async_retry(
        max_attempts=3,
        initial_backoff=1.0,
        multiplier=2.0,
        max_backoff=10.0,
        on=(Exception,),  # httpx.HTTPError + OSError + TimeoutError
    )
    if make_async_retry is not None
    else (lambda f: f)
)


@dataclass(slots=True)
class AsyncSoapClient:
    """Минимальный async SOAP-клиент.

    S163 W4: обёрнут в ``_SOAP_BREAKER.guard()`` для защиты от каскадных
    failures при недоступности SOAP-эндпоинта.

    Attrs:
        endpoint: URL SOAP-сервиса (ConcretePort).
        soap_action: SOAPAction-header или пустая строка.
        timeout: Таймаут запроса.
    """

    endpoint: str
    soap_action: str = ""
    timeout: float = 30.0

    async def _do_call(
        self, envelope_xml: str, headers: dict[str, str] | None = None
    ) -> str:
        """Внутренняя SOAP call с retry-обёрткой.

        S168 W10 P1-7: добавлен ``httpx.Limits`` для connection pool
        (по умолчанию httpx 100/20 — risk of FD exhaustion под burst).
        Per-call client оставлен для backward-compat (custom cert/timeout
        per endpoint), но с явным ``Limits`` чтобы не выходить за
        разумные границы.
        """
        import httpx

        hdr = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": self.soap_action,
        }
        if headers:
            hdr.update(headers)
        # S168 W10 P1-7: явный connection pool limits
        # (max_connections=50, max_keepalive_connections=20 — SOAP burst
        # обычно ≤20 RPS; httpx default 100/20 перебор для per-call).
        limits = httpx.Limits(
            max_connections=50, max_keepalive_connections=20
        )
        async with httpx.AsyncClient(
            http2=True, timeout=self.timeout, limits=limits
        ) as client:
            resp = await client.post(
                self.endpoint, content=envelope_xml.encode("utf-8"), headers=hdr
            )
            resp.raise_for_status()
            return resp.text

    @_soap_retry
    async def call(
        self, envelope_xml: str, headers: dict[str, str] | None = None
    ) -> str:
        """Отправляет SOAP-envelope, возвращает raw XML-ответ."""
        async with _SOAP_BREAKER.guard():
            return await self._do_call(envelope_xml, headers)

    @staticmethod
    def parse_envelope(xml_str: str) -> Any:
        """Парсит XML-ответ в lxml.etree-дерево."""
        from lxml import etree

        return etree.fromstring(xml_str.encode("utf-8"), resolve_entities=False)
