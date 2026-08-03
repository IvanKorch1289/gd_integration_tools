"""S60 W2 — client.py part of cdc decomp.

Classes: CDCClient.

CDCClient (main client, 7 methods).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,  # S60 W2: cross-import
    CDCSubscription,  # S60 W2: cross-import
)
from src.backend.infrastructure.clients.external.cdc.kafka_strategy import (
    _KafkaDebeziumStrategy,  # S166 W1: cross-import (S167 W1.1 wired)
)
from src.backend.infrastructure.clients.external.cdc.strategies import (
    _CDCStrategy,  # S60 W2: cross-import
    _ListenNotifyStrategy,  # S60 W2: cross-import
    _LogMinerStrategy,  # S60 W2: cross-import
    _PollingStrategy,  # S60 W2: cross-import
)

if TYPE_CHECKING:
    from src.backend.infrastructure.messaging.dlq_base import DLQWriter

logger = get_logger("infrastructure.clients.cdc")


# S102 W1: module-level singleton holder. До этого момента
# ``get_cdc_client()`` падал с NameError на ``_cdc_instance``
# (pre-existing bug с S60 W2 — был определён в client.py, но
# потерян при decomp из monolithic cdc.py). Lock добавляет
# thread-safety для concurrent first-call.
import threading

_cdc_instance: CDCClient | None = None  # type: ignore[name-defined]  # noqa: F821
_cdc_lock = threading.Lock()


class CDCClient:
    """Клиент CDC — управление подписками на изменения.

    Поддерживает 4 стратегии: polling, listen_notify, logminer, kafka.
    """

    _STRATEGIES: dict[str, type[_CDCStrategy]] = {
        "polling": _PollingStrategy,
        "listen_notify": _ListenNotifyStrategy,
        "logminer": _LogMinerStrategy,
        "kafka": _KafkaDebeziumStrategy,  # S166 W1: re-added в S167 W1.1
    }

    def __init__(self, *, dlq_writer: DLQWriter | None = None) -> None:
        self._subscriptions: dict[str, CDCSubscription] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        # B-02 fix (S176 cycle 33): DLQ handoff on callback/dispatch failure.
        # When set, exceptions in ``_dispatch_change`` no longer silently
        # drop the event — they are serialized as ``DLQEnvelope`` and written
        # via ``dlq_writer.write(envelope)``. Composition root wires the
        # writer via :meth:`set_dlq_writer` (singleton-friendly).
        self._dlq_writer: DLQWriter | None = dlq_writer

    def set_dlq_writer(self, writer: DLQWriter | None) -> None:
        """Установить/сбросить DLQ-writer (для composition root wiring).

        B-02 fix (S176 cycle 33): singleton-инстанс, полученный через
        :func:`get_cdc_client`, не имеет доступа к ``__init__``-аргументам;
        этот метод позволяет wiring-слою установить writer пост-фактум.
        """
        self._dlq_writer = writer

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
            except (asyncio.CancelledError, Exception):
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
        """Обрабатывает обнаруженное изменение.

        B-02 fix (S176 cycle 33): на исключение в callback или
        ``action_handler_registry.dispatch()`` событие сериализуется в
        :class:`DLQEnvelope` (reason=``UNEXPECTED``) и отправляется в
        ``dlq_writer`` если он сконфигурирован. Без writer — fallback
        к ERROR-логу (поведение pre-fix). Исключения никогда не
        пробрасываются, чтобы consumer-loop не падал на одном
        poison-message.
        """
        event_dict = event.to_dict()

        if sub.callback:
            try:
                await sub.callback(event_dict)
            except Exception as exc:
                logger.error("CDC callback error [%s]: %s", sub.id, exc)
                await self._send_to_dlq(
                    sub, event_dict, exc, stage="callback"
                )

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
                await self._send_to_dlq(
                    sub, event_dict, exc, stage="dispatch"
                )

    async def _send_to_dlq(
        self,
        sub: CDCSubscription,
        event_dict: dict[str, Any],
        exc: BaseException,
        *,
        stage: str,
    ) -> None:
        """Отправить failed event в DLQ (B-02 fix).

        Lazy import :class:`DLQEnvelope` / :class:`DLQReason` чтобы
        не создавать циклическую зависимость с messaging-слоем на
        import-time. Если DLQ сам упал — событие логируется с
        ``exc_info`` и не пробрасывается (consumer-loop не должен
        падать из-за сбоя нижестоящей системы).
        """
        if self._dlq_writer is None:
            # No DLQ wired — pre-fix behavior (log + drop). Operators
            # should configure ``set_dlq_writer`` in production; в
            # тестах-одиночках можно явно передать writer в ``__init__``.
            return

        try:
            from src.backend.infrastructure.messaging.dlq_base import (
                DLQEnvelope,
                DLQReason,
            )

            envelope = DLQEnvelope(
                transport=f"cdc:{sub.profile}",
                route_id=f"{sub.profile}.{event_dict.get('table', '?')}",
                original_payload=event_dict,
                error_class=type(exc).__name__,
                error_message=f"{stage} failed: {exc}",
                reason=DLQReason.UNEXPECTED,
                metadata={
                    "stage": stage,
                    "subscription_id": sub.id,
                    "profile": sub.profile,
                    "strategy": sub.strategy,
                    "table": event_dict.get("table"),
                    "operation": event_dict.get("operation"),
                },
            )
        except Exception as build_exc:  # noqa: BLE001
            # Envelope build failed (should not happen, but defensive):
            # log + drop, never propagate.
            logger.exception(
                "CDC DLQ envelope build failed [%s stage=%s]: %s",
                sub.id, stage, build_exc,
            )
            return

        try:
            await self._dlq_writer.write(envelope)
            logger.warning(
                "CDC event forwarded to DLQ after %s failure "
                "[subscription=%s table=%s]",
                stage, sub.id, event_dict.get("table"),
            )
        except Exception as dlq_exc:  # noqa: BLE001
            logger.exception(
                "CDC DLQ handoff failed [%s stage=%s]: %s — EVENT WILL BE LOST",
                sub.id, stage, dlq_exc,
            )

    async def shutdown(self) -> None:
        """Останавливает все подписки."""
        for sub_id in list(self._subscriptions):
            await self.unsubscribe(sub_id)


def get_cdc_client() -> CDCClient:
    """Фабрика CDC-клиента (singleton, thread-safe).

    S102 W1: добавлен ``_cdc_lock`` (threading.Lock) для concurrent
    first-call safety. ``_cdc_instance`` теперь явно объявлен на
    module level (раньше — NameError, см. ADR-0186).
    """
    global _cdc_instance
    if _cdc_instance is None:
        with _cdc_lock:
            # Double-checked locking
            if _cdc_instance is None:
                _cdc_instance = CDCClient()
    return _cdc_instance


def reset_cdc_client() -> None:
    """Сбрасывает singleton (для tests). S102 W1."""
    global _cdc_instance
    with _cdc_lock:
        _cdc_instance = None
