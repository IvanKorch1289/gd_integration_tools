"""Подписчик ``events.health`` → ``NotificationGateway`` (Wave 6.4).

Слушает переходы overall-статуса от ``HealthAggregator`` и шлёт алерт
через шаблон ``health_degraded`` в дефолтный канал ``NotificationGateway``.

Активируется в ``infrastructure.application.lifecycle.startup`` через
``HealthAlertSubscriber.start()``.
"""

import logging
from typing import Any

__all__ = ("HealthAlertSubscriber",)

logger = logging.getLogger("services.health.alert")


class HealthAlertSubscriber:
    """Минимальный async-подписчик EventBus health-канала."""

    CHANNEL = "events.health"
    TEMPLATE_KEY = "health_degraded"

    def __init__(self) -> None:
        self._started = False

    async def start(self) -> None:
        """Регистрирует обработчик в FastStream Redis broker."""
        if self._started:
            return
        try:
            from src.backend.core.providers_registry import get_provider

            bus = get_provider("event_bus", "default")
            broker = getattr(bus, "_broker", None)
            if broker is None:
                logger.debug("EventBus broker not initialized — subscriber idle")
                return

            broker.subscriber(self.CHANNEL)(self._handle)
            self._started = True
            logger.info("HealthAlertSubscriber subscribed to %s", self.CHANNEL)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HealthAlertSubscriber.start failed: %s", exc)

    async def _handle(self, payload: dict[str, Any]) -> None:
        """Шлёт алерт через NotificationGateway, если статус ухудшился."""
        previous = payload.get("previous_status", "")
        current = payload.get("current_status", "")
        if not _is_degradation(previous, current):
            return
        try:
            from src.backend.core.providers_registry import get_provider

            gateway = get_provider("notifier", "gateway")
            await gateway.send(
                channel="default",
                template_key=self.TEMPLATE_KEY,
                locale="ru",
                context={
                    "previous": previous,
                    "current": current,
                    "components": payload.get("components", {}),
                },
                recipient="ops",
                priority="tx",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Health alert dispatch failed: %s", exc)


_SEVERITY_RANK = {"ok": 0, "degraded": 1, "down": 2}


def _is_degradation(previous: str, current: str) -> bool:
    """True если ``current`` строго хуже ``previous``."""
    return _SEVERITY_RANK.get(current, 0) > _SEVERITY_RANK.get(previous, 0)
