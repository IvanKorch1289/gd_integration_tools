"""EventBusFacade — capability-checked фасад шины событий.

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

__all__ = ("EventBusFacade",)

_logger = get_logger("services.messaging.eventbus_facade")

CapabilityChecker = Callable[[str, str, str | None], None]


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
            _logger.warning(
                "EventBusFacade publish failed channel=%s: %s", channel, exc
            )
            raise ServiceError(f"eventbus publish failed: {exc}") from exc

    async def subscribe(self, channel: str, handler: Any) -> Any:
        """Подписаться на канал.

        Raises:
            CapabilityDeniedError: недостаточно прав.
            ServiceError: ошибка backend'а.
        """
        self._assert_subscribe(channel)
        try:
            return await self._bus.subscribe(channel, handler)
        except Exception as exc:
            _logger.warning(
                "EventBusFacade subscribe failed channel=%s: %s", channel, exc
            )
            raise ServiceError(f"eventbus subscribe failed: {exc}") from exc

    async def subscribe_with_lifecycle(
        self,
        channel: str,
        handler: Any,
        *,
        topic_pattern: str | None = None,
        ack_mode: str = "auto",
    ) -> Any:
        """Subscribe with lifecycle tracking for graceful shutdown.

        Registers the handler and tracks it for cleanup via
        ``unsubscribe_all()``. Used by DSL processor wiring and
        startup hooks.

        Args:
            channel: EventBus channel to subscribe to.
            handler: Async callback ``async (event) -> None``.
            topic_pattern: Original DSL topic pattern (for metadata).
            ack_mode: ``"auto"`` or ``"manual"``.

        Returns:
            Subscription handle or None.
        """
        self._assert_subscribe(channel)
        try:
            result = await self._bus.subscribe(channel, handler)
            self._subscriptions.append(
                _SubscriptionRecord(
                    channel=channel,
                    handler=handler,
                    topic_pattern=topic_pattern,
                    ack_mode=ack_mode,
                )
            )
            _logger.info(
                "EventBusFacade subscribe_with_lifecycle channel=%s pattern=%s",
                channel,
                topic_pattern,
            )
            return result
        except Exception as exc:
            _logger.warning(
                "EventBusFacade subscribe_with_lifecycle failed channel=%s: %s",
                channel,
                exc,
            )
            raise ServiceError(f"eventbus subscribe failed: {exc}") from exc

    async def unsubscribe_all(self) -> None:
        """Unsubscribe all lifecycle-tracked subscriptions.

        Called during graceful shutdown to clean up consumers.
        Calls bus.unsubscribe() for each tracked handler.
        """
        count = len(self._subscriptions)
        if count == 0:
            return
        _logger.info("EventBusFacade unsubscribe_all: %d subscriptions", count)
        for sub in self._subscriptions:
            try:
                if hasattr(self._bus, "unsubscribe"):
                    await self._bus.unsubscribe(sub.channel, sub.handler)
            except Exception as exc:
                _logger.warning(
                    "EventBusFacade unsubscribe failed channel=%s: %s", sub.channel, exc
                )
        self._subscriptions.clear()

    @property
    def subscription_count(self) -> int:
        """Number of active lifecycle-tracked subscriptions."""
        return len(self._subscriptions)

    async def request(
        self,
        channel: str,
        payload: dict[str, Any],
        *,
        timeout: float = 30.0,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Request-Reply через EventBus.

        Raises:
            CapabilityDeniedError: недостаточно прав.
            ServiceError: ошибка backend'а.
        """
        self._assert_publish(channel)
        try:
            return await self._bus.request(
                channel, payload, timeout=timeout, correlation_id=correlation_id
            )
        except Exception as exc:
            _logger.warning(
                "EventBusFacade request failed channel=%s: %s", channel, exc
            )
            raise ServiceError(f"eventbus request failed: {exc}") from exc

    async def publish_generic(
        self,
        channel: str,
        topic: str,
        payload: dict[str, Any] | list[Any] | str | int | float | bool | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Публикация generic event (DSL convenience method)."""
        from src.backend.infrastructure.clients.messaging.event_bus import GenericEvent

        self._assert_publish(channel)
        event = GenericEvent(
            topic=topic, payload=payload, correlation_id=correlation_id
        )
        try:
            await self._bus.publish(channel, event)
        except Exception as exc:
            _logger.warning("EventBusFacade publish_generic failed: %s", exc)
            raise ServiceError(f"eventbus publish_generic failed: {exc}") from exc
