"""K3 W2 — NATSJetStreamSource: durable consumer через NATS JetStream.

Реализует входящий источник поверх NATS JetStream с поддержкой
durable consumers (pull-модель). Lazy-import ``nats`` — библиотека
добавляется в pyproject.toml в S3 cutover (Wave 3).

Под feature-flag ``nats_jetstream_dsl`` (default-OFF).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.source import SourceEvent, SourceKind
from src.backend.infrastructure.logging.factory import get_logger

if TYPE_CHECKING:
    pass

__all__ = ("NATSJetStreamSource", "NATSMessage")

logger = get_logger("infrastructure.sources.nats_jetstream")


@dataclass(slots=True)
class NATSMessage:
    """Входящее сообщение от NATS JetStream.

    Args:
        subject: Subject (тема), из которого пришло сообщение.
        data: Сырые байты payload.
        headers: Заголовки сообщения (опционально).
        reply: Reply-subject (для request/reply паттерна).
        timestamp: Время получения сообщения.
    """

    subject: str
    data: bytes
    headers: dict[str, str] | None = None
    reply: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class NATSJetStreamSource:
    """Источник событий из NATS JetStream с durable consumer pull-моделью.

    Подключается к NATS-серверу, получает JetStream context и
    создаёт или привязывается к существующему durable consumer.
    Сообщения доставляются через async-iterator с автоматическим ack.

    Args:
        subject: Subject (тема) NATS JetStream для подписки.
        stream: Имя JetStream stream.
        durable: Имя durable consumer (гарантирует возобновляемость).
        nats_url: URL NATS-сервера (default: ``nats://localhost:4222``).
    """

    kind: SourceKind = SourceKind.MQ

    def __init__(
        self,
        subject: str,
        stream: str,
        durable: str,
        nats_url: str = "nats://localhost:4222",
    ) -> None:
        self.source_id: str = f"nats_js:{stream}:{durable}"
        self._subject = subject
        self._stream = stream
        self._durable = durable
        self._nats_url = nats_url
        self._nc: Any = None  # NATS connection
        self._lock = asyncio.Lock()
        self._running = False

    async def stream(self) -> AsyncIterator[NATSMessage]:
        """Durable consumer pull: бесконечный async-iterator сообщений.

        Выполняет fetch по одному сообщению и ack после обработки.
        При ошибке подключения — логирует и завершает итерацию.

        Yields:
            :class:`NATSMessage` для каждого входящего сообщения.
        """
        try:
            import nats
        except ImportError as exc:
            raise ImportError(
                "nats-py не установлен. Добавьте 'nats-py>=2.7' в зависимости "
                "(S3 Wave 3 cutover). Временно используйте pytest.importorskip('nats')."
            ) from exc

        async with self._lock:
            if self._nc is not None:
                raise RuntimeError(
                    f"NATSJetStreamSource(stream={self._stream!r}, "
                    f"durable={self._durable!r}) уже запущен"
                )
            self._nc = await nats.connect(self._nats_url)
            self._running = True

        logger.info(
            "NATSJetStreamSource: подключён к %s, stream=%s, durable=%s",
            self._nats_url,
            self._stream,
            self._durable,
        )

        try:
            js = self._nc.jetstream()
            psub = await js.pull_subscribe(
                self._subject, durable=self._durable, stream=self._stream
            )

            while self._running:
                try:
                    msgs = await psub.fetch(1, timeout=5.0)
                except Exception as fetch_exc:
                    # Timeout или transient-ошибка — продолжаем цикл
                    logger.debug(
                        "NATSJetStreamSource fetch timeout/error (stream=%s): %s",
                        self._stream,
                        fetch_exc,
                    )
                    continue

                for msg in msgs:
                    headers: dict[str, str] | None = None
                    if msg.headers:
                        headers = dict(msg.headers)

                    nats_msg = NATSMessage(
                        subject=msg.subject,
                        data=msg.data,
                        headers=headers,
                        reply=msg.reply or None,
                        timestamp=datetime.now(UTC),
                    )
                    yield nats_msg
                    await msg.ack()

        except GeneratorExit:
            logger.debug(
                "NATSJetStreamSource: iterator закрыт (stream=%s)", self._stream
            )
        finally:
            await self._close()

    async def start(self, on_event: Any) -> None:
        """Запускает приём событий через callback (Source-контракт).

        Каждое сообщение конвертируется в :class:`SourceEvent` и
        передаётся в ``on_event``.

        Args:
            on_event: Async-callback, вызываемый на каждое событие.
        """
        async for nats_msg in self.stream():
            event = SourceEvent(
                source_id=self.source_id,
                kind=self.kind,
                payload=nats_msg.data,
                timestamp=nats_msg.timestamp,
                metadata={
                    "subject": nats_msg.subject,
                    "stream": self._stream,
                    "durable": self._durable,
                    "headers": nats_msg.headers or {},
                    "reply": nats_msg.reply,
                },
            )
            try:
                await on_event(event)
            except Exception as exc:
                logger.error(
                    "NATSJetStreamSource on_event failed (stream=%s): %s",
                    self._stream,
                    exc,
                )

    async def stop(self) -> None:
        """Корректно останавливает источник (отписка + disconnect)."""
        self._running = False
        await self._close()

    async def health(self) -> bool:
        """Быстрая проверка: соединение с NATS установлено."""
        return self._nc is not None and not self._nc.is_closed

    async def fetch_consumer_info(self) -> dict[str, Any]:
        """Снимок состояния durable consumer (S13 K3 W5).

        Возвращает словарь:
        ``{"pending_messages": int, "delivered_consumer_seq": int,
        "delivered_stream_seq": int, "ack_floor_consumer_seq": int,
        "ack_floor_stream_seq": int}``.

        Используется в Streamlit-панели для визуализации lag'а.
        """
        if self._nc is None or self._nc.is_closed:
            return {
                "stream": self._stream,
                "durable": self._durable,
                "error": "disconnected",
                "pending_messages": 0,
            }
        try:
            js = self._nc.jetstream()
            info = await js.consumer_info(self._stream, self._durable)
            delivered = getattr(info, "delivered", None)
            ack_floor = getattr(info, "ack_floor", None)
            return {
                "stream": self._stream,
                "durable": self._durable,
                "pending_messages": int(getattr(info, "num_pending", 0)),
                "delivered_consumer_seq": int(
                    getattr(delivered, "consumer_seq", 0) if delivered else 0
                ),
                "delivered_stream_seq": int(
                    getattr(delivered, "stream_seq", 0) if delivered else 0
                ),
                "ack_floor_consumer_seq": int(
                    getattr(ack_floor, "consumer_seq", 0) if ack_floor else 0
                ),
                "ack_floor_stream_seq": int(
                    getattr(ack_floor, "stream_seq", 0) if ack_floor else 0
                ),
            }
        except Exception as exc:
            return {
                "stream": self._stream,
                "durable": self._durable,
                "error": str(exc),
                "pending_messages": 0,
            }

    async def _close(self) -> None:
        """Закрывает NATS-соединение если открыто."""
        async with self._lock:
            nc = self._nc
            self._nc = None
        if nc is not None:
            try:
                await nc.drain()
            except Exception as exc:
                logger.warning("NATSJetStreamSource drain error: %s", exc)
            finally:
                try:
                    await nc.close()
                except Exception as exc:
                    logger.warning("NATSJetStreamSource close error: %s", exc)
