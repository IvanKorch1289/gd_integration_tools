"""K3 W2 — NATSJetStreamSink: публикация в NATS JetStream.

Реализует исходящий Sink для публикации сообщений в NATS JetStream.
Lazy-import ``nats`` — библиотека добавляется в pyproject.toml в S3
cutover (Wave 3). Без установленной библиотеки ``publish`` возвращает
``SinkResult(ok=False)`` — graceful как остальные Sink-ы.

Под feature-flag ``nats_jetstream_dsl`` (default-OFF).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import orjson

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.logging import get_logger
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
    timeout: float = 10.0
    kind: SinkKind = field(default=SinkKind.NATS_JS, init=False)

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

    async def health(self) -> bool:
        """Health: подключение к NATS без публикации (CONNECT/DISCONNECT)."""
        try:
            import nats
        except ImportError:
            return False
        nc = None
        try:
            nc = await nats.connect(self.nats_url)
            return True
        except Exception as _:
            return False
        finally:
            if nc is not None:
                try:
                    await nc.close()
                except Exception as _hc_exc:
                    logger.debug("NATSJetStreamSink health close error: %s", _hc_exc)
