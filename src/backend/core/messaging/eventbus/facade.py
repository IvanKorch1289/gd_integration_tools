"""EventBusFacade — capability-checked фасад шины событий (S31 Task 3).

S31 Task 3: Promoted from ``services/messaging/eventbus_facade.py`` to
``core/messaging/eventbus/facade.py`` for architectural consistency
(extensions/DSL should access messaging через core, not services).

Скрывает выбор backend'а (Redis/Kafka/NATS) за единым API для extensions
и DSL-процессоров. Является canonical entry point для домена messaging.

Контракт:
* publish-операции требуют capability ``messaging.publish.<channel>``;
* subscribe-операции требуют capability ``messaging.subscribe.<channel>``.

При отсутствии ``capability_check`` (unit-тесты) — capability-проверка
пропускается.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.backend.core.errors import ServiceError
from src.backend.core.logging import get_logger

__all__ = ("CapabilityChecker", "EventBusFacade", "get_event_bus_facade")

_logger = get_logger("core.messaging.eventbus.facade")

CapabilityChecker = Callable[[str, str, str | None], None]


def get_event_bus_facade() -> EventBusFacade:
    """S205 + S31 Task 3: lazy singleton-аксессор :class:`EventBusFacade`.

    Returns:
        EventBusFacade инстанс, инициализированный через ``get_event_bus()``.
        Без capability_check — публикация доступна всему коду (tests /
        system-level integrations). В production передаётся ``capability_check``
        через :func:`register_event_bus_facade_capability_check`.

    Notes:
        Не thread-safe singleton — caller ответственен за вызов из одного
        места. Для FastAPI lifespan рекомендуется ``register_event_bus_facade``.
    """
    from src.backend.infrastructure.clients.messaging.event_bus import get_event_bus

    return EventBusFacade(event_bus=get_event_bus())


@dataclass
class _SubscriptionRecord:
    """Internal record for lifecycle-managed subscriptions."""

    channel: str
    handler: Any
    topic_pattern: str | None = None
    ack_mode: str = "auto"


class EventBusFacade:
    """Capability-checked фасад шины событий для extensions.

    Args:
        event_bus: Backend-agnostic :class:`EventBus` (обычно из ``get_event_bus()``).
        capability_check: Опц. callback ``CapabilityGate.check``.
        plugin: Имя caller'а (для capability-event и audit).
    """

    def __init__(
        self,
        event_bus: Any,
        *,
        capability_check: CapabilityChecker | None = None,
        plugin: str = "extension",
    ) -> None:
        self._bus = event_bus
        self._check = capability_check
        self._plugin = plugin
        self._subscriptions: list[_SubscriptionRecord] = []

    def _assert_publish(self, channel: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "messaging.publish", channel)

    def _assert_subscribe(self, channel: str) -> None:
        if self._check is not None:
            self._check(self._plugin, "messaging.subscribe", channel)

    async def publish(self, channel: str, event: Any) -> None:
        """Опубликовать событие в канал.

        Raises:
            CapabilityDeniedError: недостаточно прав.
            ServiceError: ошибка backend'а.
        """
        self._assert_publish(channel)
        try:
            await self._bus.publish(channel, event)
        except Exception as exc:
            raise ServiceError(f"publish failed: {exc}") from exc

    async def subscribe(self, channel: str, handler: Any) -> Any:
        """Подписаться на канал с handler.

        Returns:
            Subscription token (для unsubscribe).
        """
        self._assert_subscribe(channel)
        return await self._bus.subscribe(channel, handler)

    async def subscribe_with_lifecycle(
        self,
        channel: str,
        handler: Any,
        *,
        topic_pattern: str | None = None,
        ack_mode: str = "auto",
    ) -> None:
        """Подписаться с автоматическим unsubscribe через facade.shutdown().

        Args:
            channel: Канал подписки (или pattern).
            handler: Async callable, вызывается на каждое событие.
            topic_pattern: Опциональный glob-pattern (для topic-based routing).
            ack_mode: ``"auto"`` (auto-ack) / ``"manual"`` (handler должен ack).

        Raises:
            CapabilityDeniedError: недостаточно прав.
        """
        self._assert_subscribe(channel)
        await self._bus.subscribe(channel, handler)
        self._subscriptions.append(
            _SubscriptionRecord(
                channel=channel,
                handler=handler,
                topic_pattern=topic_pattern,
                ack_mode=ack_mode,
            ),
        )

    async def unsubscribe_all(self) -> None:
        """Отписаться от всех зарегистрированных подписок (lifecycle)."""
        for record in self._subscriptions:
            try:
                await self._bus.unsubscribe(record.channel, record.handler)
            except Exception as exc:  # pragma: no cover
                _logger.warning(
                    "eventbus_facade.unsubscribe_failed: channel=%s exc=%s",
                    record.channel,
                    exc,
                )
        self._subscriptions.clear()

    async def request(
        self,
        channel: str,
        payload: Any,
        *,
        timeout: float = 30.0,
        correlation_id: str | None = None,
    ) -> Any:
        """Request/reply pattern — publish + wait for response.

        Args:
            channel: Канал для публикации.
            payload: Payload для request.
            timeout: Таймаут ожидания reply (сек).
            correlation_id: Optional explicit correlation_id (default: random UUID).

        Returns:
            Reply payload from the awaited handler.

        Raises:
            asyncio.TimeoutError: При превышении ``timeout``.
        """
        self._assert_publish(channel)
        return await self._bus.request(
            channel,
            payload,
            timeout=timeout,
            correlation_id=correlation_id,
        )

    async def publish_generic(
        self,
        event: Any,
        *,
        channel: str | None = None,
    ) -> None:
        """Опубликовать pre-built event (ChannelEnvelope-like объект).

        Args:
            event: Pre-built event object (должен иметь ``.channel`` attribute
                если ``channel`` не передан явно).
            channel: Explicit channel override.
        """
        target_channel = channel or getattr(event, "channel", None)
        if target_channel is None:
            raise ServiceError("publish_generic: channel must be explicit or in event")
        await self.publish(target_channel, event)

    @property
    def subscription_count(self) -> int:
        """Число активных подписок (для observability)."""
        return len(self._subscriptions)
