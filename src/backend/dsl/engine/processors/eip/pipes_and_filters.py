"""Pipes and Filters EIP processor (Sprint 56 W1).

Apache Camel Pipes and Filters:
https://camel.apache.org/components/latest/eips/pipes-and-filters.html

Конвейер независимых фильтров-преобразователей. Каждое сообщение проходит
через цепочку шагов (pipes), каждый шаг может:

* transform body (output → input следующего шага);
* short-circuit (``stop`` на exchange — pipeline terminates);
* ничего не делать (no-op passthrough).

Отличие от ``Routing Slip``: routing_slip — динамический per-message список
endpoint'ов; pipes-and-filters — статическая декларативная цепочка
transformation steps (compile-time DSL).

Использование в DSL::

    from src.backend.dsl.engine.processors.eip.pipes_and_filters import (
        PipesAndFiltersProcessor,
    )

    .process(PipesAndFiltersProcessor(steps=[
        parse_xml_step,
        validate_step,
        enrich_step,
        normalize_step,
    ]))

Или через DSL builder (см. S56 W1.2)::

    .pipeline(parse_xml, validate, enrich, normalize)

Thread-safe: steps фиксированы в __init__; lock только для shared stats.
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("PipesAndFiltersProcessor",)

_log = get_logger(__name__)


# Type alias: filter step получает exchange, может (опционально) вернуть
# новый body. Если возвращает None — body остаётся прежним.
FilterStep = Callable[[Exchange[Any]], Any | None | Awaitable[Any | None]]


class PipesAndFiltersProcessor(BaseProcessor):
    """Конвейер transformation filters (Camel Pipes and Filters).

    Каждое сообщение проходит через цепочку ``steps`` последовательно.
    Output каждого step (если вернул value) становится input следующего.

    Args:
        steps: упорядоченный список filter step callables. Каждый step
            получает ``Exchange`` и опционально возвращает новый body
            (``None`` = passthrough). Sync и async step'ы оба поддерживаются.
        propagate_failure: если ``True`` (default) — failed step прерывает
            pipeline. Если ``False`` — error logged, pipeline continues.
        name: имя процессора.

    Properties (на exchange):
        * ``pipes_filters.total_steps`` — len(steps).
        * ``pipes_filters.completed`` — кол-во выполненных шагов.
        * ``pipes_filters.last_step`` — индекс последнего выполненного.

    Example::

        async def parse_xml(ex):
            ex.in_message.body = xmltodict.parse(ex.in_message.body)
            return ex.in_message.body

        async def validate(ex):
            if "id" not in ex.in_message.body:
                raise ValueError("missing id")
            return ex.in_message.body

        PipesAndFiltersProcessor(steps=[parse_xml, validate])
    """

    def __init__(
        self,
        steps: list[FilterStep],
        *,
        propagate_failure: bool = True,
        name: str | None = None,
    ) -> None:
        if not steps:
            raise ValueError("PipesAndFiltersProcessor requires at least one step")
        super().__init__(name=name or "pipes_and_filters")
        self._steps = list(steps)
        self._propagate_failure = propagate_failure
        self._lock = threading.Lock()
        self._invocations = 0
        self._failures = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        total = len(self._steps)
        exchange.set_property("pipes_filters.total_steps", total)
        exchange.set_property("pipes_filters.completed", 0)
        exchange.set_property("pipes_filters.last_step", -1)

        with self._lock:
            self._invocations += 1

        for idx, step in enumerate(self._steps):
            try:
                result = step(exchange)
                if _isawaitable(result):
                    # mypy: result narrowed to Awaitable[Any] by _isawaitable
                    awaited: Any = await result  # type: ignore[misc]
                    result = awaited
                if result is not None:
                    exchange.in_message.body = result
                exchange.set_property("pipes_filters.completed", idx + 1)
                exchange.set_property("pipes_filters.last_step", idx)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._failures += 1
                _log.warning(
                    "PipesAndFilters[%d/%d] %s: step raised %s",
                    idx + 1,
                    total,
                    getattr(step, "__name__", repr(step)),
                    exc,
                )
                if self._propagate_failure:
                    raise
                # else: log + continue
            if exchange.stopped:
                _log.debug(
                    "PipesAndFilters: pipeline stopped at step %d/%d", idx + 1, total
                )
                break

    def stats(self) -> dict[str, int]:
        """Snapshot of invocations/failures counters."""
        with self._lock:
            return {"invocations": self._invocations, "failures": self._failures}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "pipes_and_filters",
            "steps": len(self._steps),
            "propagate_failure": self._propagate_failure,
        }


def _isawaitable(value: Any) -> bool:
    """Helper: check if value is awaitable (coroutine / Future)."""
    import inspect

    return inspect.isawaitable(value)
