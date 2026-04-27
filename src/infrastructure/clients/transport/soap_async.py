"""Async SOAP-клиент на httpx + lxml (C11, ADR-009).

Альтернатива zeep (sync, deprecated). Для простых SOAP-вызовов
(одиночный POST XML envelope без сложных WSDL-инклюдов) этого
достаточно; для продвинутых сценариев — `aiohttp-soap` (включено в
extras гуманитарно).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

__all__ = ("AsyncSoapClient",)

logger = logging.getLogger("transport.soap_async")


@dataclass(slots=True)
class AsyncSoapClient:
    """Минимальный async SOAP-клиент.

    Attrs:
        endpoint: URL SOAP-сервиса (ConcretePort).
        soap_action: SOAPAction-header или пустая строка.
        timeout: Таймаут запроса.
    """

    endpoint: str
    soap_action: str = ""
    timeout: float = 30.0

    async def call(
        self, envelope_xml: str, headers: dict[str, str] | None = None
    ) -> str:
        """Отправляет SOAP-envelope, возвращает raw XML-ответ."""
        import httpx

        hdr = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": self.soap_action,
        }
        if headers:
            hdr.update(headers)
        async with httpx.AsyncClient(http2=True, timeout=self.timeout) as client:
            resp = await client.post(
                self.endpoint, content=envelope_xml.encode("utf-8"), headers=hdr
            )
            resp.raise_for_status()
            return resp.text

    @staticmethod
    def parse_envelope(xml_str: str) -> Any:
        """Парсит XML-ответ в lxml.etree-дерево."""
        from lxml import etree

        return etree.fromstring(xml_str.encode("utf-8"))
