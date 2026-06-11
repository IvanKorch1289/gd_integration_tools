from __future__ import annotations

"""S60 W2 — client.py part of cdc decomp.

Classes: CDCClient.

CDCClient (main client, 7 methods).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,  # S60 W2: cross-import
    CDCSubscription,  # S60 W2: cross-import
)
from src.backend.infrastructure.clients.external.cdc.strategies import (
    _CDCStrategy,  # S60 W2: cross-import
    _ListenNotifyStrategy,  # S60 W2: cross-import
    _LogMinerStrategy,  # S60 W2: cross-import
    _PollingStrategy,  # S60 W2: cross-import
)


class CDCClient:
    """Клиент CDC — управление подписками на изменения.

    Поддерживает 3 стратегии: polling, listen_notify, logminer.
    """

    _STRATEGIES: dict[str, type[_CDCStrategy]] = {
        "polling": _PollingStrategy,
        "listen_notify": _ListenNotifyStrategy,
        "logminer": _LogMinerStrategy,
    }

    def __init__(self) -> None:
        self._subscriptions: dict[str, CDCSubscription] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    async def subscribe(
        self,
        profile: str,
        tables: list[str],
        *,
        strategy: str = "polling",
        interval: float = 5.0,
        batch_size: int = 100,
        timestamp_column: str = "updated_at",
        channel: str | None = None,
        callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        target_action: str | None = None,
    ) -> str:
        """Создаёт подписку на изменения в таблицах.

        Args:
            profile: Имя профиля внешней БД.
            tables: Список таблиц для отслеживания.
            strategy: polling | listen_notify | logminer.
            interval: Интервал polling (сек).
            batch_size: Макс. событий за итерацию.
            timestamp_column: Столбец для polling-стратегии.
            channel: PG LISTEN-канал (по умолчанию cdc_<table>).
            callback: Async-функция обработки событий.
            target_action: Action для диспетчеризации при событии.

        Returns:
            ID подписки.
        """
        if strategy not in self._STRATEGIES:
            raise ValueError(
                f"Unknown CDC strategy '{strategy}'. Available: {list(self._STRATEGIES)}"
            )

        sub = CDCSubscription(
            profile=profile,
            tables=tables,
            strategy=strategy,
            interval=interval,
            batch_size=batch_size,
            timestamp_column=timestamp_column,
            channel=channel,
            callback=callback,
            target_action=target_action,
        )
        self._subscriptions[sub.id] = sub

        strategy_impl = self._STRATEGIES[strategy]()
        task = get_task_registry().create_task(
            self._run_strategy(strategy_impl, sub), name=f"cdc-{sub.id}"
        )
        self._tasks[sub.id] = task

        logger.info(
            "CDC подписка создана: id=%s profile=%s tables=%s strategy=%s",
            sub.id,
            profile,
            tables,
            strategy,
        )
        return sub.id

    async def _run_strategy(self, strategy: _CDCStrategy, sub: CDCSubscription) -> None:
        """Запускает стратегию и ловит cancellation."""
        try:
            await strategy.run(sub, self._dispatch_change)
        except asyncio.CancelledError:
            logger.debug("CDC strategy cancelled: %s", sub.id)
        except Exception as exc:
            logger.error("CDC strategy crashed [%s]: %s", sub.id, exc, exc_info=True)

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Удаляет подписку."""
        sub = self._subscriptions.pop(subscription_id, None)
        if sub is None:
            return False

        sub.active = False
        task = self._tasks.pop(subscription_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError, Exception:
                logger.debug("CDC subscription task cancellation raised", exc_info=True)

        logger.info("CDC подписка удалена: %s", subscription_id)
        return True

    def list_subscriptions(self) -> list[dict[str, Any]]:
        """Возвращает список активных подписок."""
        return [
            {
                "id": sub.id,
                "profile": sub.profile,
                "tables": sub.tables,
                "strategy": sub.strategy,
                "target_action": sub.target_action,
                "active": sub.active,
            }
            for sub in self._subscriptions.values()
        ]

    async def _dispatch_change(self, sub: CDCSubscription, event: CDCEvent) -> None:
        """Обрабатывает обнаруженное изменение."""
        event_dict = event.to_dict()

        if sub.callback:
            try:
                await sub.callback(event_dict)
            except Exception as exc:
                logger.error("CDC callback error [%s]: %s", sub.id, exc)

        if sub.target_action:
            from src.backend.dsl.commands.registry import action_handler_registry
            from src.backend.schemas.invocation import ActionCommandSchema

            command = ActionCommandSchema(
                action=sub.target_action,
                payload=event_dict,
                meta={"source": f"cdc:{sub.profile}:{sub.strategy}"},
            )
            try:
                await action_handler_registry.dispatch(command)
            except Exception as exc:
                logger.error(
                    "CDC dispatch error [%s -> %s]: %s", sub.id, sub.target_action, exc
                )

    async def shutdown(self) -> None:
        """Останавливает все подписки."""
        for sub_id in list(self._subscriptions):
            await self.unsubscribe(sub_id)


def get_cdc_client() -> CDCClient:
    """Фабрика CDC-клиента (singleton)."""
    global _cdc_instance
    if _cdc_instance is None:
        _cdc_instance = CDCClient()
    return _cdc_instance
