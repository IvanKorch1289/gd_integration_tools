"""ForwardToProcessor — outbound pass-through в backend-сервис.

Wave 3.5. Полагается на уже существующие клиенты проекта:
* HTTP → ``httpx.AsyncClient`` (как в ``HttpCallProcessor``).
* SOAP → вызов поверх того же httpx (XML body raw-pass).
* gRPC → generic bytes-pipe (unary) через ``grpc.aio`` (опционально).
* Queue (kafka/rabbit/redis) → ``StreamClient.publish_to_<protocol>``.

Никаких (де)сериализаций, кроме жёстко необходимых для транспорта.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.processors.base import BaseProcessor
from app.dsl.engine.processors.proxy.headers import HeaderMapPolicy

__all__ = ("ForwardToProcessor", "ProxyOutboundSpec")

_logger = logging.getLogger("dsl.proxy.forward")


@dataclass(slots=True)
class ProxyOutboundSpec:
    """Нормализованный target прокси-шага."""

    protocol: str
    target: str
    pass_headers: bool = True
    header_policy: HeaderMapPolicy = field(default_factory=HeaderMapPolicy)
    rewrite_path: str | None = None
    timeout_s: float = 30.0


class ForwardToProcessor(BaseProcessor):
    """Пересылает текущее ``exchange.in_message`` в ``dst``.

    ``dst`` определяет протокол по схеме URL / префиксу:

      * ``http://...`` / ``https://...`` — HTTP;
      * ``soap://host/path`` — SOAP (httpx с XML body);
      * ``grpc://host:port/service/method`` — gRPC (optional);
      * ``kafka:<topic>``, ``rabbit:<queue>``, ``redis:<stream>`` — queue-to-queue.

    Args:
        dst: Target endpoint.
        pass_headers: Передавать ли headers из Exchange как есть
            (с учётом ``header_policy``).
        header_policy: Правила добавления/удаления/переопределения headers.
        rewrite_path: Опциональный шаблон path-rewrite для HTTP
            (``{{request.path}}`` и т.п.). ``None`` = не переписывать.
        timeout: Секунд ждать backend.
        name: Имя процессора в трассе.
    """

    def __init__(
        self,
        dst: str,
        *,
        pass_headers: bool = True,
        header_policy: HeaderMapPolicy | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        protocol, target = _split_target(dst)
        self._spec = ProxyOutboundSpec(
            protocol=protocol,
            target=target,
            pass_headers=pass_headers,
            header_policy=header_policy or HeaderMapPolicy(),
            rewrite_path=rewrite_path,
            timeout_s=timeout,
        )

    @property
    def spec(self) -> ProxyOutboundSpec:
        return self._spec

    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        body = exchange.in_message.body
        headers = (
            self._spec.header_policy.apply(exchange.in_message.headers or {})
            if self._spec.pass_headers
            else dict(self._spec.header_policy.add)
        )
        proto = self._spec.protocol
        if proto in {"http", "https"}:
            await self._forward_http(body, headers, exchange, context)
        elif proto == "soap":
            await self._forward_soap(body, headers, exchange)
        elif proto == "grpc":
            await self._forward_grpc(body, headers, exchange)
        elif proto in {"kafka", "rabbit", "redis"}:
            await self._forward_queue(proto, body, headers, exchange)
        else:
            raise ValueError(f"Неподдерживаемый target protocol: {proto!r}")

    # -- HTTP / HTTPS ------------------------------------------------

    async def _forward_http(
        self,
        body: Any,
        headers: dict[str, str],
        exchange: Exchange[Any],
        context: ExecutionContext,
    ) -> None:
        import httpx

        method = str(exchange.in_message.headers.get("X-Proxy-Method", "POST")).upper()
        target_url = self._rewrite(exchange, context)
        async with httpx.AsyncClient(timeout=self._spec.timeout_s) as client:
            resp = await client.request(
                method=method,
                url=target_url,
                content=body if isinstance(body, (bytes, bytearray, str)) else None,
                json=body if isinstance(body, (dict, list)) else None,
                headers=headers,
            )
        exchange.in_message.body = resp.content
        exchange.in_message.headers = dict(resp.headers)

    def _rewrite(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> str:
        base = f"{self._spec.protocol}://{self._spec.target}"
        if not self._spec.rewrite_path:
            return base
        mapping = {
            "request.path": str(
                exchange.in_message.headers.get("X-Proxy-Path", "")
            ),
            "request.query": str(
                exchange.in_message.headers.get("X-Proxy-Query", "")
            ),
            "route_id": context.route_id or "",
        }
        rewritten = self._spec.rewrite_path
        for key, value in mapping.items():
            rewritten = rewritten.replace(f"{{{{{key}}}}}", value)
        return base + rewritten if rewritten.startswith("/") else base + "/" + rewritten

    # -- SOAP ---------------------------------------------------------

    async def _forward_soap(
        self, body: Any, headers: dict[str, str], exchange: Exchange[Any]
    ) -> None:
        import httpx

        headers.setdefault("Content-Type", "text/xml; charset=utf-8")
        url = f"http://{self._spec.target}"
        async with httpx.AsyncClient(timeout=self._spec.timeout_s) as client:
            resp = await client.post(
                url,
                content=body if isinstance(body, (bytes, bytearray, str)) else str(body),
                headers=headers,
            )
        exchange.in_message.body = resp.content
        exchange.in_message.headers = dict(resp.headers)

    # -- gRPC ---------------------------------------------------------

    async def _forward_grpc(
        self, body: Any, headers: dict[str, str], exchange: Exchange[Any]
    ) -> None:
        try:
            import grpc  # noqa: F401
            from grpc import aio as grpc_aio
        except ImportError as exc:
            raise RuntimeError("grpcio не установлен — gRPC-proxy недоступен") from exc

        host, _, method = self._spec.target.partition("/")
        if not method:
            raise ValueError(
                "grpc target должен быть 'host:port/package.Service/Method'"
            )
        metadata = tuple(headers.items())
        async with grpc_aio.insecure_channel(host) as channel:
            # generic unary-unary через сырые bytes.
            call = channel.unary_unary(
                f"/{method}",
                request_serializer=lambda x: x if isinstance(x, bytes) else bytes(x),
                response_deserializer=lambda x: x,
            )
            response = await call(
                body if isinstance(body, (bytes, bytearray)) else bytes(body),
                metadata=metadata,
                timeout=self._spec.timeout_s,
            )
        exchange.in_message.body = response

    # -- Queue-to-queue ----------------------------------------------

    async def _forward_queue(
        self,
        protocol: str,
        body: Any,
        headers: dict[str, str],
        exchange: Exchange[Any],  # noqa: ARG002
    ) -> None:
        from app.infrastructure.clients.messaging.stream import get_stream_client

        client = get_stream_client()
        payload = body if isinstance(body, dict) else {"body": body}
        if protocol == "kafka":
            await client.publish_to_kafka(
                topic=self._spec.target, message=payload, headers=headers
            )
        elif protocol == "rabbit":
            await client.publish_to_rabbit(queue=self._spec.target, message=payload)
        elif protocol == "redis":
            await client.publish_to_redis(
                stream=self._spec.target, message=payload, headers=headers
            )


def _split_target(raw: str) -> tuple[str, str]:
    if "://" in raw:
        proto, target = raw.split("://", 1)
        return proto.lower(), target
    if ":" in raw:
        proto, target = raw.split(":", 1)
        if proto.lower() in {"kafka", "rabbit", "redis", "grpc", "soap"}:
            return proto.lower(), target
    raise ValueError(
        f"ForwardToProcessor.dst должен быть '<protocol>://<target>' или "
        f"'<queue>:<dest>', получено {raw!r}"
    )
