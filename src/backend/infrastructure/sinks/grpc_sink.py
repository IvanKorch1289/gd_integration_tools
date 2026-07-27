"""GrpcSink — outbound unary gRPC call (Wave 3.1).

Минимальная унарная отправка: открыть канал, вызвать method,
прочитать ответ, закрыть. Сериализация — JSON по умолчанию
(``payload`` → bytes), для строгих proto-схем используется
fully-qualified ``service`` + ``method`` имена. Ленивый импорт
``grpc.aio`` — extra ``grpc``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.resilience.connector_breaker import with_breaker
from src.backend.core.resilience.connector_retry import with_retry
from src.backend.core.security.connector_auth import require_capability
from src.backend.dsl.codec.json import dumps_bytes
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.security.connector_rate_limiter import (
    get_connector_rate_limiter,
)
from src.backend.infrastructure.sinks._timeouts import DEFAULT_SINK_TIMEOUT_S

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
    timeout: float = DEFAULT_SINK_TIMEOUT_S  # Cycle 12: externalized to sinks/_timeouts
    secure: bool = True
    metadata: list[tuple[str, str]] = field(default_factory=list)
    kind: SinkKind = field(default=SinkKind.GRPC, init=False)

    @with_breaker("grpc_sink")
    @with_retry(max_attempts=3)
    @require_capability("grpc.invoke", action="write")
    async def send(self, payload: Any) -> SinkResult:
        """Открывает канал, вызывает unary RPC и возвращает ответ."""
        # S1: per-connector rate limit. Scope — per-method для изоляции.
        limiter = get_connector_rate_limiter()
        limiter.register(f"{self.sink_id}_grpc", "60/s", 60)
        await limiter.check(f"{self.sink_id}_grpc", scope=self.full_method)

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
        except ImportError:
            # ImportError is non-retryable: surface as SinkResult(ok=False).
            return SinkResult(ok=False, details={"error": "grpcio not installed"})
        # Cycle 22 P1-6: let transport exceptions propagate so the
        # @with_retry / @with_breaker decorators on send() can see them.
        # Previously, except Exception returned SinkResult(ok=False) which
        # bypassed retry/breaker entirely.

        return SinkResult(
            ok=True,
            details={
                "method": self.full_method,
                "response_bytes": len(response) if response else 0,
            },
        )

    async def health(self, mode: str = "fast") -> HealthResult:
        """Health: попытка установить gRPC-канал и сразу закрыть."""
        try:
            from grpc import aio as grpc_aio
            from grpc import ssl_channel_credentials
        except ImportError:
            return HealthResult.failed(error="grpcio not installed", mode=mode)
        start = time.perf_counter()
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
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
        latency_ms = (time.perf_counter() - start) * 1000.0
        return HealthResult.ok(latency_ms=latency_ms, mode=mode)
