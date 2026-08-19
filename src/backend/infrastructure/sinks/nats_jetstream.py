"""K3 W2 — NATSJetStreamSink: публикация в NATS JetStream.

Реализует исходящий Sink для публикации сообщений в NATS JetStream.
Lazy-import ``nats`` — библиотека добавляется в pyproject.toml в S3
cutover (Wave 3). Без установленной библиотеки ``publish`` возвращает
``SinkResult(ok=False)`` — graceful как остальные Sink-ы.

Под feature-flag ``nats_jetstream_dsl`` (default-OFF).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import orjson

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.logging import get_logger
from src.backend.core.resilience.connector_breaker import with_breaker
from src.backend.core.resilience.retry import with_retry
from src.backend.core.security.connector_auth import require_capability
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.security.connector_rate_limiter import (
    get_connector_rate_limiter,
)
from src.backend.infrastructure.sinks._timeouts import DEFAULT_SINK_TIMEOUT_S

__all__ = ("NATSJetStreamSink",)

logger = get_logger("infrastructure.sinks.nats_jetstream")


@dataclass(slots=True)
class NATSJetStreamSink(Sink):
    """Sink публикации сообщений в NATS JetStream.

    Каждый вызов ``send``/``publish`` создаёт кратковременное соединение
    с NATS-сервером (connect → publish → drain → close). Для высоконагруженных
    сценариев рекомендуется использовать connection pool (Wave R2).

    Args:
        sink_id: Уникальный идентификатор.
        nats_url: URL NATS-сервера.
        default_subject: Целевой subject по умолчанию (для ``send``).
        timeout: Таймаут connect/publish в секундах.

    """

    sink_id: str
    nats_url: str = "nats://localhost:4222"
    default_subject: str = ""
    timeout: float = DEFAULT_SINK_TIMEOUT_S  # Cycle 12: externalized to sinks/_timeouts
    kind: SinkKind = field(default=SinkKind.NATS_JS, init=False)

    @with_breaker("nats_js_sink")
    @with_retry(max_attempts=5, retry_on=(ConnectionError, TimeoutError, OSError))
    @require_capability("nats.write", action="write")
    async def publish(
        self, subject: str, data: bytes, headers: dict[str, str] | None = None
    ) -> SinkResult:
        """Публикует ``data`` в JetStream subject с опциональными headers.

        Args:
            subject: Целевой subject (тема) JetStream.
            data: Байты payload для публикации.
            headers: Заголовки NATS-сообщения (опционально).

        Returns:
            :class:`SinkResult` с флагом успеха и метаданными.

        """
        # S1: per-connector rate limit. Scope — per-subject для изоляции.
        limiter = get_connector_rate_limiter()
        limiter.register(f"{self.sink_id}_nats_js", "200/s", 200)
        await limiter.check(f"{self.sink_id}_nats_js", scope=subject)

        try:
            import nats
        except ImportError:
            return SinkResult(ok=False, details={"error": "nats-py not installed"})

        nc = None
        try:
            nc = await nats.connect(self.nats_url)
            js = nc.jetstream()
            ack = await js.publish(subject, data, headers=headers or None)
        except Exception as exc:
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )
        finally:
            if nc is not None:
                try:
                    await nc.drain()
                except Exception as _drain_exc:
                    logger.debug("NATSJetStreamSink drain error: %s", _drain_exc)
                try:
                    await nc.close()
                except Exception as _close_exc:
                    logger.debug("NATSJetStreamSink close error: %s", _close_exc)

        return SinkResult(
            ok=True,
            external_id=str(ack.seq) if ack else None,
            details={
                "subject": subject,
                "stream": ack.stream if ack else None,
                "seq": ack.seq if ack else None,
            },
        )

    async def send(self, payload: Any) -> SinkResult:
        """Публикует ``payload`` в ``default_subject`` (Sink-контракт).

        ``payload`` сериализуется через :func:`dumps_bytes` (orjson)
        если это не ``bytes``/``str``.

        Args:
            payload: Полезная нагрузка (dict/bytes/str).

        Returns:
            :class:`SinkResult` с флагом успеха.

        """
        if not self.default_subject:
            return SinkResult(
                ok=False,
                details={"error": "default_subject не задан — используйте publish()"},
            )

        if isinstance(payload, (bytes, bytearray)):
            data: bytes = bytes(payload)
        elif isinstance(payload, str):
            data = payload.encode()
        else:
            data = orjson.dumps(payload)

        return await self.publish(self.default_subject, data)

    async def health(self, mode: str = "fast") -> HealthResult:
        """Health: подключение к NATS без публикации (CONNECT/DISCONNECT)."""
        try:
            import nats
        except ImportError:
            return HealthResult.failed(error="nats-py not installed", mode=mode)
        start = time.perf_counter()
        nc = None
        try:
            nc = await nats.connect(self.nats_url)
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
        finally:
            if nc is not None:
                try:
                    await nc.close()
                except Exception as _hc_exc:
                    logger.debug("NATSJetStreamSink health close error: %s", _hc_exc)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return HealthResult.ok(latency_ms=latency_ms, mode=mode)
