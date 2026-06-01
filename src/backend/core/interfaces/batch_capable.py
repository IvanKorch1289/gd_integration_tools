"""W14.2 — opt-in Protocol для процессоров с batch-семантикой.

Процессор, реализующий :class:`BatchCapable`, явно объявляет, что умеет
обработать список событий за один вызов. Engine при ``Message.data_kind ==
BATCH`` предпочитает ``process_batch`` обычному ``process`` — это снимает
overhead вызова per-item и позволяет векторизовать обработку (polars/numpy).

Процессоры без этого Protocol — engine разворачивает batch в цикл
``for item in batch.body: await processor.process(...)``.

Контракт умышленно минимален: один метод ``process_batch``, без callback'ов
и состояния — всё через ``ExecutionContext``, как и в обычном ``process``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("BatchCapable",)


@runtime_checkable
class BatchCapable(Protocol):
    """Процессор, оптимизированный под batch-обработку.

    Methods:
        process_batch: Обработать пачку сообщений за один вызов.
            ``exchange.in_message.body`` — список items;
            ``exchange.in_message.data_kind`` — должен быть ``DataKind.BATCH``.
    """

    async def process_batch(
        self, exchange: Exchange[list[Any]], context: ExecutionContext
    ) -> None: ...
