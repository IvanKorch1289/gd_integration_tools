"""W23 — Контракты универсальных DSL-Sources.

Определяют единый интерфейс ``Source`` для 10 типов входящих каналов:
HTTP/Webhook, SOAP, gRPC, WebSocket, MQ (Kafka/RabbitMQ/NATS/Redis-Streams),
CDC (PG logical replication), File/Dir Watcher, Polling.

Контракт минимален и стабилен: ``start(on_event)`` запускает приём,
каждое входящее событие транслируется через async-callback. Реальные
бэкенды живут в ``infrastructure/sources/<kind>/`` и регистрируются
в :class:`SourceRegistry` (services/sources/registry.py).

Адаптация Source → Invoker делается отдельным
:class:`SourceToInvokerAdapter` — Source ничего не знает про Invoker.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

__all__ = ("SourceKind", "SourceEvent", "EventCallback", "Source")


class SourceKind(str, Enum):
    """Тип входящего источника.

    Один Gateway покрывает все варианты, конкретный бэкенд выбирается
    по полю ``kind`` в YAML-spec.
    """

    HTTP = "http"
    WEBHOOK = "webhook"
    SOAP = "soap"
    GRPC = "grpc"
    WEBSOCKET = "websocket"
    MQ = "mq"
    CDC = "cdc"
    FILE_WATCHER = "file_watcher"
    POLLING = "polling"


@dataclass(slots=True)
class SourceEvent:
    """Унифицированное событие, эмитируемое Source.

    Args:
        source_id: Идентификатор source-инстанса (из YAML-spec).
        kind: Тип источника (для observability и роутинга).
        payload: Полезная нагрузка (тело webhook, MQ-сообщение, ...).
        event_time: Время события (если backend не знает — wall-clock).
        event_id: Глобально-уникальный id; используется для idempotency.
        metadata: headers/offset/correlation-id и пр. — зависит от backend.
    """

    source_id: str
    kind: SourceKind
    payload: Any
    event_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)


EventCallback = Callable[[SourceEvent], Awaitable[None]]
"""Async-callback, принимающий одно событие. Source гарантирует await."""


@runtime_checkable
class Source(Protocol):
    """Универсальный контракт входящего канала (W23 Gateway).

    Жизненный цикл: ``start(on_event)`` → приём событий → ``stop()``.
    Идемпотентность ``start``/``stop`` оставлена на усмотрение реализации,
    но повторный ``start`` без ``stop`` обязан бросить ``RuntimeError``.

    Реализации:

    * ``infrastructure.sources.webhook.WebhookSource`` — HTTP+HMAC.
    * ``infrastructure.sources.mq.MQSource`` — Kafka/Rabbit/NATS/Redis.
    * ``infrastructure.sources.file_watcher.FileWatcherSource`` — FS.
    * ``infrastructure.sources.polling.PollingSource`` — APScheduler+HTTP.
    * ``infrastructure.sources.cdc.CDCSource`` — PG logical replication.
    * ... и др. по ``SourceKind``.
    """

    source_id: str
    kind: SourceKind

    async def start(self, on_event: EventCallback) -> None:
        """Начать приём событий. Каждое событие → ``await on_event(...)``.

        Args:
            on_event: Async-callback, вызываемый на каждое входящее
                событие. Source обязан ловить исключения callback и не
                ронять собственный loop.
        """
        ...

    async def stop(self) -> None:
        """Корректно остановить приём (release ресурсов, отписки)."""
        ...

    async def health(self) -> bool:
        """Быстрая проверка работоспособности (для health-aggregator)."""
        ...
