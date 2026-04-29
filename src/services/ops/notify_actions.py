"""Wiring action-handler'ов поверх ``NotificationGateway`` (Wave 8.3).

Старые action-spec'ы (``notify.email``, ``notify.telegram``, ...) указывают
на ``services.ops.notification_hub`` — он помечен deprecated и уйдёт
в H3_PLUS. Этот модуль даёт замену: фасад ``NotifyGatewayActions``
с теми же именами методов, но реализованный поверх нового
``NotificationGateway``.

Использование:

```python
from src.dsl.commands.action_registry import action_handler_registry
from src.services.ops.notify_actions import register_notify_actions

register_notify_actions(action_handler_registry, prefix="notifyv2")
```

Вызов `register_notify_actions(..., override=True)` подменит существующие
``notify.*`` при поэтапной миграции.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from src.dsl.commands.action_registry import ActionHandlerRegistry

__all__ = (
    "NotifyGatewayActions",
    "get_notify_gateway_actions",
    "register_notify_actions",
)


@dataclass(slots=True)
class NotifyGatewayActions:
    """Фасад над ``NotificationGateway`` для action-dispatcher'а.

    Все методы принимают одинаковые kwargs (передаются как есть в gateway).
    Метод ``send_tx``/``send`` — общая точка входа, остальные — sugar
    с зафиксированным каналом.
    """

    async def _send(self, *, channel: str, **kwargs: Any) -> Any:
        from src.core.providers_registry import get_provider

        gateway = get_provider("notifier", "gateway")
        return await gateway.send(channel=channel, **kwargs)

    async def send(self, *, channel: str = "email", **kwargs: Any) -> Any:
        """Универсальный send — channel передаётся в kwargs."""
        return await self._send(channel=channel, **kwargs)

    async def email(self, **kwargs: Any) -> Any:
        return await self._send(channel="email", **kwargs)

    async def telegram(self, **kwargs: Any) -> Any:
        return await self._send(channel="telegram", **kwargs)

    async def slack(self, **kwargs: Any) -> Any:
        return await self._send(channel="slack", **kwargs)

    async def teams(self, **kwargs: Any) -> Any:
        return await self._send(channel="teams", **kwargs)

    async def sms(self, **kwargs: Any) -> Any:
        return await self._send(channel="sms", **kwargs)

    async def webhook(self, **kwargs: Any) -> Any:
        return await self._send(channel="webhook", **kwargs)

    async def express(self, **kwargs: Any) -> Any:
        return await self._send(channel="express", **kwargs)


_actions: NotifyGatewayActions | None = None


def get_notify_gateway_actions() -> NotifyGatewayActions:
    """Lazy singleton фасада."""
    global _actions
    if _actions is None:
        _actions = NotifyGatewayActions()
    return _actions


def register_notify_actions(
    registry: ActionHandlerRegistry,
    *,
    prefix: str = "notifyv2",
    override: bool = False,
) -> list[str]:
    """Регистрирует action'ы ``<prefix>.email``, ``<prefix>.telegram``...

    Args:
        registry: Целевой реестр.
        prefix: Префикс имён action'ов. По умолчанию ``notifyv2``.
        override: Если True — регистрирует в виде ``notify.<channel>``,
            заменяя legacy-handlers. Используется при поэтапной миграции.

    Returns:
        Список зарегистрированных имён action'ов.
    """
    from src.dsl.commands.action_registry import ActionHandlerSpec

    channels = ("email", "telegram", "slack", "teams", "sms", "webhook", "express")
    base_prefix = "notify" if override else prefix

    specs: list[ActionHandlerSpec] = [
        ActionHandlerSpec(
            action=f"{base_prefix}.send",
            service_getter=get_notify_gateway_actions,
            service_method="send",
        )
    ]
    for ch in channels:
        specs.append(
            ActionHandlerSpec(
                action=f"{base_prefix}.{ch}",
                service_getter=get_notify_gateway_actions,
                service_method=ch,
            )
        )
    registry.register_many(specs)
    return [s.action for s in specs]
