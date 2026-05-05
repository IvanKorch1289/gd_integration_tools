"""Wave 6.3 — Composed Message Processor (последний EIP, 30/30).

Camel pattern: входное сообщение разбивается ``splitter`` на N частей,
каждая часть обрабатывается одним и тем же sub-pipeline (``processors``),
затем результаты собираются ``aggregator`` обратно в одно сообщение.

В отличие от Splitter+ScatterGather, тут:
* splitter — произвольный callable, не jmespath-выражение;
* aggregator — произвольный callable, который сам формирует итоговый
  Exchange (например, sum / merge / join_strings и т.п.);
* sub-processors применяются строго последовательно к каждой части.

Контракт DSL::

    .composed_message(
        splitter=my_split,                    # (Exchange) -> list[Exchange]
        processors=[ProcA(), ProcB()],
        aggregator=my_aggregate,              # (list[Exchange]) -> Exchange
    )

``to_spec`` возвращает ``None``, если splitter / aggregator — callable
(round-trip не поддерживается; sub-processors сохраняются информационно).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("ComposedMessageProcessor",)


SplitterCallable = Callable[
    [Exchange[Any]], "list[Exchange[Any]] | Awaitable[list[Exchange[Any]]]"
]
AggregatorCallable = Callable[
    [list[Exchange[Any]]], "Exchange[Any] | Awaitable[Exchange[Any]]"
]


async def _maybe_await(value: Any) -> Any:
    """Await, если это coroutine/awaitable; иначе вернёт как есть."""
    import inspect

    if inspect.isawaitable(value):
        return await value
    return value


class ComposedMessageProcessor(BaseProcessor):
    """EIP «Composed Message Processor» — split → per-part processing → aggregate.

    Args:
        splitter: Callable ``(exchange) -> list[Exchange]``. Может быть
            sync или async. Если результат — пустой список, аggregator
            вызывается с пустым списком (без обработки sub-processors).
        processors: Список процессоров, каждый из которых применяется
            к каждому sub-Exchange по очереди.
        aggregator: Callable ``(list[Exchange]) -> Exchange``. Получает
            список обработанных sub-exchange и должен вернуть итоговый
            Exchange. Может быть sync или async.
        name: Опциональное имя.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        splitter: SplitterCallable,
        processors: list[BaseProcessor],
        aggregator: AggregatorCallable,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "composed_message")
        self._splitter = splitter
        self._processors = list(processors)
        self._aggregator = aggregator

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Разбивает входящий ``exchange`` через splitter, прогоняет каждую часть через sub-processors и собирает aggregator'ом."""
        try:
            parts = await _maybe_await(self._splitter(exchange))
        except Exception as exc:  # noqa: BLE001
            exchange.set_error(f"composed_message split failed: {exc}")
            exchange.fail(f"composed_message split failed: {exc}")
            return

        if not isinstance(parts, list):
            exchange.fail("composed_message: splitter must return list[Exchange]")
            return

        processed: list[Exchange[Any]] = []
        for part in parts:
            if not isinstance(part, Exchange):
                # Допускаем частичную совместимость — оборачиваем dict/str/etc как body.
                part = Exchange(
                    in_message=Message(
                        body=part, headers=dict(exchange.in_message.headers)
                    )
                )

            if part.status == ExchangeStatus.pending:
                part.status = ExchangeStatus.processing

            for proc in self._processors:
                if part.status == ExchangeStatus.failed or part.stopped:
                    break
                await proc.process(part, context)

            processed.append(part)

        try:
            aggregated = await _maybe_await(self._aggregator(processed))
        except Exception as exc:  # noqa: BLE001
            exchange.set_error(f"composed_message aggregate failed: {exc}")
            exchange.fail(f"composed_message aggregate failed: {exc}")
            return

        if not isinstance(aggregated, Exchange):
            exchange.fail("composed_message: aggregator must return Exchange")
            return

        # Переносим результаты aggregated → текущий exchange.
        body = (
            aggregated.out_message.body
            if aggregated.out_message is not None
            else aggregated.in_message.body
        )
        headers = (
            dict(aggregated.out_message.headers)
            if aggregated.out_message is not None
            else dict(aggregated.in_message.headers)
        )
        exchange.set_out(body=body, headers=headers)
        exchange.set_property("composed_part_count", len(processed))

    def to_spec(self) -> dict[str, Any] | None:
        """Round-trip не поддерживается — splitter/aggregator всегда callable."""
        return None
