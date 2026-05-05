"""ExposeProxyProcessor — inbound-биндинг прокси-роута.

Wave 3.5. Регистрирует, что текущий роут выступает как тонкий прокси:
принимает вход (HTTP/SOAP/gRPC/queue) и кладёт тело + метаданные
запроса в Exchange. Ничего не сериализует/не парсит — байты идут as-is,
где это возможно.

Этот процессор не инициирует listen-сокет сам по себе — реальный
listener поднимается соответствующим entrypoint-слоем (REST router,
SOAP handler, gRPC server, StreamClient subscriber) по сведениям из
``RouteRegistry``. Задача процессора — зафиксировать source-spec
и нормализовать ``exchange.in_message`` для последующего ``forward_to``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.proxy.headers import HeaderMapPolicy

__all__ = ("ExposeProxyProcessor", "ProxyInboundSpec")

ProtocolLiteral = Literal["http", "soap", "grpc", "kafka", "rabbit", "redis"]


@dataclass(slots=True)
class ProxyInboundSpec:
    """Нормализованная привязка входа прокси-роута.

    ``src`` формата ``<protocol>:<address>``. Допустимые варианты:
      * ``http:/api/payments`` — путь FastAPI-роутера.
      * ``soap:/ws/payments`` — SOAP endpoint.
      * ``grpc:/payments.Service/Method`` — gRPC метод (generic).
      * ``kafka:orders.in`` / ``rabbit:orders-in`` / ``redis:orders.stream``
        — очередь-источник.
    """

    protocol: ProtocolLiteral
    address: str
    methods: tuple[str, ...] = ()
    header_policy: HeaderMapPolicy = field(default_factory=HeaderMapPolicy)


class ExposeProxyProcessor(BaseProcessor):
    """Декларирует inbound-биндинг прокси-роута.

    Args:
        src: Строка ``<protocol>:<address>``.
        methods: HTTP-методы (только для ``http``). None = все.
        header_policy: Политика header-map-а на inbound-стороне.
        name: Имя процессора в трассе.
    """

    def __init__(
        self,
        src: str,
        *,
        methods: list[str] | tuple[str, ...] | None = None,
        header_policy: HeaderMapPolicy | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        protocol, address = _split_endpoint(src)
        self._spec = ProxyInboundSpec(
            protocol=protocol,
            address=address,
            methods=tuple(m.upper() for m in (methods or ())),
            header_policy=header_policy or HeaderMapPolicy(),
        )

    @property
    def spec(self) -> ProxyInboundSpec:
        return self._spec

    async def process(
        self,
        exchange: Exchange[Any],
        context: ExecutionContext,  # noqa: ARG002
    ) -> None:
        # Нормализуем headers согласно политике — последующий forward_to
        # получает уже очищенный набор.
        headers = exchange.in_message.headers or {}
        exchange.in_message.headers = self._spec.header_policy.apply(headers)
        exchange.set_property("_proxy_inbound", self._spec)


def _split_endpoint(raw: str) -> tuple[ProtocolLiteral, str]:
    if ":" not in raw:
        raise ValueError(
            f"ExposeProxyProcessor.src должен быть '<protocol>:<address>', получено {raw!r}"
        )
    proto, address = raw.split(":", 1)
    proto = proto.lower()
    if proto not in {"http", "soap", "grpc", "kafka", "rabbit", "redis"}:
        raise ValueError(f"Неподдерживаемый protocol в proxy src: {proto!r}")
    return proto, address  # type: ignore[return-value]
