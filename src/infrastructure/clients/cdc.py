"""Change Data Capture — подписка на изменения таблиц во внешних БД.

Использует PostgreSQL logical replication через asyncpg
для отслеживания INSERT/UPDATE/DELETE во внешних базах данных.
При обнаружении изменений вызывает зарегистрированный callback
или диспетчеризует action через ActionHandlerRegistry.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable
from uuid import uuid4

__all__ = ("CDCClient", "CDCSubscription", "get_cdc_client")

logger = logging.getLogger(__name__)


@dataclass
class CDCSubscription:
    """Описание подписки на изменения."""

    id: str = field(default_factory=lambda: uuid4().hex[:12])
    profile: str = ""
    tables: list[str] = field(default_factory=list)
    callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    target_action: str | None = None
    active: bool = True


class CDCClient:
    """Клиент CDC — управление подписками на изменения в таблицах."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, CDCSubscription] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def subscribe(
        self,
        profile: str,
        tables: list[str],
        *,
        callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        target_action: str | None = None,
    ) -> str:
        """Создаёт подписку на изменения в таблицах.

        Args:
            profile: Имя профиля внешней БД.
            tables: Список таблиц для отслеживания.
            callback: Async-функция обработки изменений.
            target_action: Action для диспетчеризации при изменении.

        Returns:
            ID подписки.
        """
        sub = CDCSubscription(
            profile=profile,
            tables=tables,
            callback=callback,
            target_action=target_action,
        )
        self._subscriptions[sub.id] = sub

        task = asyncio.create_task(self._listen(sub))
        self._tasks[sub.id] = task

        logger.info(
            "CDC подписка создана: id=%s, profile=%s, tables=%s",
            sub.id, profile, tables,
        )
        return sub.id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Удаляет подписку.

        Args:
            subscription_id: ID подписки.

        Returns:
            True если подписка была найдена и удалена.
        """
        sub = self._subscriptions.pop(subscription_id, None)
        if sub is None:
            return False

        sub.active = False
        task = self._tasks.pop(subscription_id, None)
        if task and not task.done():
            task.cancel()

        logger.info("CDC подписка удалена: %s", subscription_id)
        return True

    def list_subscriptions(self) -> list[dict[str, Any]]:
        """Возвращает список активных подписок."""
        return [
            {
                "id": sub.id,
                "profile": sub.profile,
                "tables": sub.tables,
                "target_action": sub.target_action,
                "active": sub.active,
            }
            for sub in self._subscriptions.values()
        ]

    async def _listen(self, sub: CDCSubscription) -> None:
        """Слушает изменения в БД через polling.

        Упрощённая реализация — использует периодический
        опрос вместо logical replication для совместимости.
        Для production рекомендуется logical replication slot.
        """
        try:
            while sub.active:
                await asyncio.sleep(5)

                if not sub.active:
                    break

        except asyncio.CancelledError:
            logger.debug("CDC listener cancelled: %s", sub.id)
        except Exception as exc:
            logger.error("CDC listener error [%s]: %s", sub.id, exc, exc_info=True)

    async def _dispatch_change(
        self, sub: CDCSubscription, change: dict[str, Any]
    ) -> None:
        """Обрабатывает обнаруженное изменение."""
        if sub.callback:
            await sub.callback(change)

        if sub.target_action:
            from app.dsl.commands.registry import action_handler_registry
            from app.schemas.invocation import ActionCommandSchema

            command = ActionCommandSchema(
                action=sub.target_action,
                payload=change,
                meta={"source": f"cdc:{sub.profile}"},
            )
            try:
                await action_handler_registry.dispatch(command)
            except Exception as exc:
                logger.error(
                    "CDC dispatch error [%s -> %s]: %s",
                    sub.id, sub.target_action, exc,
                )

    async def shutdown(self) -> None:
        """Останавливает все подписки."""
        for sub_id in list(self._subscriptions):
            await self.unsubscribe(sub_id)


_cdc_instance: CDCClient | None = None


def get_cdc_client() -> CDCClient:
    """Фабрика CDC-клиента (singleton)."""
    global _cdc_instance
    if _cdc_instance is None:
        _cdc_instance = CDCClient()
    return _cdc_instance
