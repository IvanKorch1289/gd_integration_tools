"""GrpcSink — outbound unary gRPC call (Wave 3.1).

Минимальная унарная отправка: открыть канал, вызвать method,
прочитать ответ, закрыть. Сериализация — JSON по умолчанию
(``payload`` → bytes), для строгих proto-схем используется
fully-qualified ``service`` + ``method`` имена. Ленивый импорт
``grpc.aio`` — extra ``grpc``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.utilities.json_codec import dumps_bytes

__all__ = ("GrpcSink",)


@dataclass(slots=True)
class GrpcSink(Sink):
    """Sink для unary gRPC-вызова на внешний сервис.

    Args:
        sink_id: Уникальный идентификатор.
        target: ``host:port`` целевого сервера.
        full_method: Fully-qualified имя метода
            (``"/package.Service/Method"``).
        timeout: Дедлайн вызова в секундах.
        secure: Использовать TLS (по умолчанию ``True``).
        metadata: gRPC-metadata (как list[tuple]).

    Note:
        ``payload`` сериализуется в bytes (если не bytes уже —
        через ``json.dumps`` UTF-8). Получатель должен уметь
        читать JSON-binary; для строго типизированных proto
        используйте codegen-обёртку (Wave 1.3) и не унары через
        этот sink.
    """

    sink_id: str
    target: str
    full_method: str
    timeout: float = 10.0
    secure: bool = True
    metadata: list[tuple[str, str]] = field(default_factory=list)
    kind: SinkKind = field(default=SinkKind.GRPC, init=False)

    async def send(self, payload: Any) -> SinkResult:
        """Открывает канал, вызывает unary RPC и возвращает ответ."""
        try:
            from grpc import aio as grpc_aio
            from grpc import ssl_channel_credentials
        except ImportError:
            return SinkResult(ok=False, details={"error": "grpcio not installed"})

        body = payload if isinstance(payload, bytes) else dumps_bytes(payload)

        try:
            if self.secure:
                channel = grpc_aio.secure_channel(
                    self.target, ssl_channel_credentials()
                )
            else:
                channel = grpc_aio.insecure_channel(self.target)
            try:
                response = await channel.unary_unary(self.full_method)(
                    body, timeout=self.timeout, metadata=self.metadata or None
                )
            finally:
                await channel.close()
        except Exception as exc:  # noqa: BLE001
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )

        return SinkResult(
            ok=True,
            details={
                "method": self.full_method,
                "response_bytes": len(response) if response else 0,
            },
        )

    async def health(self) -> bool:
        """Health: попытка установить gRPC-канал и сразу закрыть."""
        try:
            from grpc import aio as grpc_aio
            from grpc import ssl_channel_credentials
        except ImportError:
            return False
        try:
            if self.secure:
                channel = grpc_aio.secure_channel(
                    self.target, ssl_channel_credentials()
                )
            else:
                channel = grpc_aio.insecure_channel(self.target)
            try:
                await channel.channel_ready()
            finally:
                await channel.close()
        except Exception:  # noqa: BLE001
            return False
        return True
