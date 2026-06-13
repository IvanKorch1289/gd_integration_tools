"""S106 W4 — ``NatsSource``: regular NATS core pub/sub source (no JetStream).

Источник поверх NATS core (без JetStream / durable consumer / ack).
Подходит для fire-and-forget pub/sub-паттернов: LLM-events, metrics,
notification fan-out, ephemeral-команды.

S106 W4 scope: skeleton — Config dataclass + class skeleton + lazy
import ``nats-py``. Реальный runtime-wiring (``stream()`` async
iterator, reconnect-loop, last-sequence resume) — S106+ W5+
(multi-wave scope). DSL entry-point ``RouteBuilder.from_nats(...)``
создаёт экземпляр для smoke-валидации (S50 W2 pattern, как
``from_webdav``).

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
from typing import TYPE_CHECKING, Any

from src.backend.core.interfaces.source import SourceKind

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ("NatsSource", "NatsMessage")


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
    timestamp: "datetime | None" = None


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
    """

    kind: SourceKind = SourceKind.MQ

    def __init__(self, subject: str, nats_url: str = "nats://localhost:4222") -> None:
        if not subject:
            raise ValueError("NatsSource: subject обязателен")
        self.source_id: str = f"nats:{subject}"
        self._subject = subject
        self._nats_url = nats_url
        self._nc: Any = None  # NATS connection (lazy)
        self._lock = asyncio.Lock()
        self._running = False

    async def stream(self) -> AsyncIterator[NatsMessage]:
        """Async-iterator по NATS-сообщениям.

        S106 W4: skeleton. Реальная реализация (subscribe + reconnect-loop)
        — S106+ W5+ (требует nats-py async client + graceful reconnect).
        """
        # Lazy import: nats-py добавляется в S3 cutover.
        # Если библиотека недоступна — runtime warning, не crash.
        try:
            import nats  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            return
        # Skeleton: no real subscribe yet. S106+ W5+ wires nats.subscribe()
        # + reconnect loop. Return type-плейсхолдер для type-checker.
        if False:  # pragma: no cover  (skeleton branch)
            yield NatsMessage(subject="", data=b"")

    async def stop(self) -> None:
        """Остановить подписку и закрыть NATS connection."""
        async with self._lock:
            self._running = False
            if self._nc is not None:
                try:
                    await self._nc.close()
                except Exception:
                    pass
                self._nc = None
