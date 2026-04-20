"""Банковские процессоры: SWIFT MT/MX, ISO 20022, FIX, EDIFACT, 1C.

Все парсеры/сериализаторы работают на уровне Exchange body. Реальные
интеграции (подписание, отправка на gateway) делегируются
зарегистрированным action'ам через `DispatchActionProcessor`.

Интеграции с госучреждениями (ЦБ РФ, СМЭВ, ЕСИА, ФНС, НБКИ) сознательно
НЕ включены: они маршрутизируются через отдельную интеграционную шину
предприятия, а не напрямую из этого сервиса.
"""

from __future__ import annotations

import re
from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "SwiftMTParserProcessor",
    "SwiftMXBuilderProcessor",
    "Iso20022ParserProcessor",
    "FixMessageProcessor",
    "EdifactParserProcessor",
    "OneCExchangeProcessor",
)


_MT_FIELD_RE = re.compile(r"^:(?P<tag>\d{2}[A-Z]?):(?P<value>.*)$", re.MULTILINE)


class SwiftMTParserProcessor(BaseProcessor):
    """Парсит SWIFT MT-сообщение (MT103, MT202, MT940) в dict-структуру.

    На вход: bytes | str в формате MT.
    На выход: {"header": {...}, "fields": {"20": "...", "32A": "...", ...}}.
    """

    def __init__(self, message_type: str = "auto") -> None:
        super().__init__(name=f"swift_mt:{message_type}")
        self.message_type = message_type

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
        fields = {m.group("tag"): m.group("value").strip() for m in _MT_FIELD_RE.finditer(text)}
        exchange.out_message.body = {
            "message_type": self.message_type,
            "fields": fields,
            "raw_length": len(text),
        }


class SwiftMXBuilderProcessor(BaseProcessor):
    """Строит SWIFT MX (ISO 20022 XML) из словаря. Делегирует в сервис через action.

    Процессор — это thin wrapper: реальный XML-генератор живёт в сервисе
    banking.swift_mx (регистрируется через @register_action).
    """

    def __init__(self, schema: str, action: str = "banking.swift_mx.build") -> None:
        super().__init__(name=f"swift_mx:{schema}")
        self.schema = schema
        self.action = action

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("swift_mx_schema", self.schema)
        exchange.set_property("banking_action", self.action)


class Iso20022ParserProcessor(BaseProcessor):
    """Парсит ISO 20022 XML (pain.001, camt.053, pacs.008) в структурированный dict.

    Использует lxml (опционально). Без lxml — поднимает ясное исключение.
    """

    def __init__(self, namespace: str | None = None) -> None:
        super().__init__(name="iso20022")
        self.namespace = namespace
        try:
            from lxml import etree  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if not self._available:
            raise RuntimeError("lxml не установлен; установи extra 'banking'")
        from lxml import etree

        body = exchange.in_message.body
        if isinstance(body, str):
            body = body.encode("utf-8")
        root = etree.fromstring(body)

        def walk(node: Any) -> dict[str, Any]:
            tag = etree.QName(node).localname
            if len(node) == 0:
                return {tag: node.text}
            return {tag: [walk(c) for c in node]}

        exchange.out_message.body = walk(root)


class FixMessageProcessor(BaseProcessor):
    """Парсер/билдер FIX-сообщений для торговых систем (биржа, брокер).

    FIX-протокол — строка вида "8=FIX.4.4|9=123|35=D|..." с SOH-разделителями.
    """

    _SOH = "\x01"

    def __init__(self, mode: str = "parse") -> None:
        super().__init__(name=f"fix:{mode}")
        if mode not in {"parse", "build"}:
            raise ValueError("mode должен быть 'parse' или 'build'")
        self.mode = mode

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if self.mode == "parse":
            text = body.decode() if isinstance(body, (bytes, bytearray)) else str(body)
            fields: dict[str, str] = {}
            for pair in text.split(self._SOH):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    fields[k] = v
            exchange.out_message.body = fields
        else:
            if not isinstance(body, dict):
                raise TypeError("FIX build ожидает dict")
            joined = self._SOH.join(f"{k}={v}" for k, v in body.items()) + self._SOH
            exchange.out_message.body = joined.encode("utf-8")


class EdifactParserProcessor(BaseProcessor):
    """Парсер UN/EDIFACT сегментов (FINPAY, PAYMUL)."""

    def __init__(self) -> None:
        super().__init__(name="edifact")

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        text = body.decode() if isinstance(body, (bytes, bytearray)) else str(body)
        segments = [s.strip() for s in text.split("'") if s.strip()]
        parsed = [{"tag": s.split("+", 1)[0], "elements": s.split("+")[1:]} for s in segments]
        exchange.out_message.body = parsed


class OneCExchangeProcessor(BaseProcessor):
    """Интеграция с 1С:Предприятие через OData или HTTP-сервисы.

    Делегирует вызов в сервис через action — реальный HTTP/OData клиент
    инициализируется в сервисе `onec.*`.
    """

    def __init__(
        self,
        operation: str,
        entity: str,
        action: str = "onec.invoke",
    ) -> None:
        super().__init__(name=f"1c:{operation}:{entity}")
        self.operation = operation
        self.entity = entity
        self.action = action

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("onec_operation", self.operation)
        exchange.set_property("onec_entity", self.entity)
        exchange.set_property("banking_action", self.action)
