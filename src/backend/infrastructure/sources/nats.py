"""S106 W4 — ``NatsSource``: regular NATS core pub/sub source (no JetStream).

Источник поверх NATS core (без JetStream / durable consumer / ack).
Подходит для fire-and-forget pub/sub-паттернов: LLM-events, metrics,
notification fan-out, ephemeral-команды.

S107 W5: real runtime — ``stream()`` async-iterator с subscribe +
reconnect-loop (max-attempts настраивается), ``start()`` callback-
обёртка для Source-контракта, ``health()`` для liveness-проб.

Отличия от :class:`NATSJetStreamSource`:

* **Нет durability** — при disconnect/subscriber-restart сообщения
  теряются (at-most-once). Для durability → ``from_nats_js``.
* **Нет ack** — subscriber не подтверждает получение.
* **Нет consumer group** — каждый подписчик получает ВСЕ сообщения
  в subject (fan-out), а не shared queue.
* **Проще конфиг** — только subject + nats_url, без stream/durable.

Требования: ``nats-py`` в pyproject.toml (S3 Wave 3 cutover, как и
JetStream variant).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.source import SourceEvent, SourceKind
from src.backend.core.logging import get_logger
if TYPE_CHECKING:
    pass

__all__ = ("NatsSource", "NatsMessage")

logger = get_logger("infrastructure.sources.nats")


@dataclass(slots=True)
class NatsMessage:
    """Входящее сообщение от NATS core (sub/unsub pattern).

    Args:
        subject: Subject (тема), из которого пришло сообщение.
        data: Сырые байты payload.
        reply: Reply-subject (для request/reply).
        timestamp: Время получения.
    """

    subject: str
    data: bytes
    reply: str | None = None
    timestamp: datetime = datetime.now(UTC)


class NatsSource:
    """Источник событий из NATS core (sub pattern, no JetStream).

    Подключается к NATS-серверу, подписывается на subject, эмитит
    :class:`NatsMessage` через async-iterator. **НЕ** durable — при
    реконнекте/рестарте subscriber'а теряются in-flight сообщения
    (at-most-once). Для durable delivery → :class:`NATSJetStreamSource`.

    Args:
        subject: Subject (тема) для подписки (wildcards ``*`` / ``>``
            поддерживаются).
        nats_url: URL NATS-сервера (default: ``nats://localhost:4222``).
        max_reconnect_attempts: Макс. попыток reconnect при обрыве
            (0 = infinite). Default: 5.
        reconnect_delay_seconds: Задержка между попытками reconnect.
            Default: 1.0.
    """

    kind: SourceKind = SourceKind.MQ

    def __init__(
        self,
        subject: str,
        nats_url: str = "nats://localhost:4222",
        max_reconnect_attempts: int = 5,
        reconnect_delay_seconds: float = 1.0,
    ) -> None:
        if not subject:
            raise ValueError("NatsSource: subject обязателен")
        if max_reconnect_attempts < 0:
            raise ValueError("NatsSource: max_reconnect_attempts >= 0")
        if reconnect_delay_seconds < 0:
            raise ValueError("NatsSource: reconnect_delay_seconds >= 0")
        self.source_id: str = f"nats:{subject}"
        self._subject = subject
        self._nats_url = nats_url
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_delay_seconds = reconnect_delay_seconds
        self._nc: Any = None  # NATS connection (lazy)
        self._lock = asyncio.Lock()
        self._running = False

    async def stream(self) -> AsyncIterator[NatsMessage]:
        """Async-iterator по NATS-сообщениям с reconnect-loop (S107 W5).

        Алгоритм:

        1. Lazy import ``nats-py`` (raise ImportError если не установлен);
        2. ``await nats.connect(nats_url)`` (single NATS connection);
        3. ``await nc.subscribe(subject)`` (подписка с auto-incoming);
        4. While running: yield :class:`NatsMessage` per incoming message;
        5. На disconnect: ``asyncio.sleep(reconnect_delay)`` + retry connect
           (max ``max_reconnect_attempts`` попыток; 0 = infinite).
        6. ``finally``: ``await nc.close()`` (graceful drain).

        Yields:
            :class:`NatsMessage` для каждого входящего сообщения.

        Raises:
            ImportError: ``nats-py`` не установлен.
            RuntimeError: max reconnect attempts exhausted.
        """
        try:
            import nats  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "nats-py not installed. Add 'nats-py>=2.7' to dependencies "
                "(S3 Wave 3 cutover). For now: pip install nats-py."
            ) from exc

        async with self._lock:
            if self._running or self._nc is not None:
                raise RuntimeError(f"NatsSource(subject={self._subject!r}) уже запущен")
            self._nc = None
            self._running = True

        reconnect_attempts = 0
        try:
            while self._running:
                try:
                    nc = await nats.connect(  # type: ignore[attr-defined]
                        self._nats_url
                    )
                    async with self._lock:
                        self._nc = nc
                    logger.info(
                        "NatsSource: подключён к %s, subject=%s",
                        self._nats_url,
                        self._subject,
                    )
                    sub = await nc.subscribe(self._subject)
                    try:
                        while self._running:
                            # nats-py: sub.next_msg() blocks с timeout
                            try:
                                msg = await sub.next_msg(timeout=5.0)
                            except Exception as fetch_exc:
                                # Timeout / cursor closed — нормальное завершение
                                # подписки, останавливаем outer loop, не reconnect.
                                logger.debug(
                                    "NatsSource.next_msg ended (subject=%s): %s",
                                    self._subject,
                                    fetch_exc,
                                )
                                self._running = False
                                break

                            nats_msg = NatsMessage(
                                subject=msg.subject,
                                data=msg.data,
                                reply=getattr(msg, "reply", None) or None,
                                timestamp=datetime.now(UTC),
                            )
                            yield nats_msg
                    finally:
                        try:
                            await sub.unsubscribe()
                        except Exception as exc:
                            logger.debug("NatsSource: unsubscribe error: %s", exc)
                    # Reset attempts на успешном завершении цикла
                    reconnect_attempts = 0
                except Exception as conn_exc:
                    logger.warning(
                        "NatsSource: connection error (attempt=%d): %s",
                        reconnect_attempts + 1,
                        conn_exc,
                    )
                    if self._max_reconnect_attempts and (
                        reconnect_attempts >= self._max_reconnect_attempts
                    ):
                        raise RuntimeError(
                            f"NatsSource: max reconnect attempts "
                            f"({self._max_reconnect_attempts}) exhausted"
                        ) from conn_exc
                    reconnect_attempts += 1
                    await asyncio.sleep(self._reconnect_delay_seconds)
        except GeneratorExit:
            logger.debug("NatsSource: iterator закрыт (subject=%s)", self._subject)
        finally:
            self._running = False
            await self._close()

    async def start(self, on_event: Any) -> None:
        """Запускает приём событий через callback (Source-контракт).

        Каждое сообщение конвертируется в :class:`SourceEvent` и
        передаётся в ``on_event``. Callback-ошибки логируются, но
        не прерывают итерацию.

        Args:
            on_event: Async-callback, вызываемый на каждое событие.
        """
        async for nats_msg in self.stream():
            event = SourceEvent(
                source_id=self.source_id,
                kind=self.kind,
                payload=nats_msg.data,
                event_time=nats_msg.timestamp,
                metadata={"subject": nats_msg.subject, "reply": nats_msg.reply},
            )
            try:
                await on_event(event)
            except Exception as exc:
                logger.error(
                    "NatsSource on_event failed (subject=%s): %s", self._subject, exc
                )

    async def stop(self) -> None:
        """Корректно останавливает источник (отписка + disconnect)."""
        self._running = False
        await self._close()

    async def health(self) -> bool:
        """Быстрая проверка: соединение с NATS установлено и открыто."""
        async with self._lock:
            nc = self._nc
        return nc is not None and not getattr(nc, "is_closed", True)

    async def _close(self) -> None:
        """Закрывает NATS-соединение если открыто."""
        async with self._lock:
            nc = self._nc
            self._nc = None
        if nc is not None:
            try:
                await nc.drain()
            except Exception as exc:
                logger.debug("NatsSource drain error: %s", exc)
            try:
                await nc.close()
            except Exception as exc:
                logger.debug("NatsSource close error: %s", exc)
