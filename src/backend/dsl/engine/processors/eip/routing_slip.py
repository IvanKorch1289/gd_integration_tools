"""Routing Slip EIP processor (Sprint 55 W1).

Apache Camel Routing Slip: https://camel.apache.org/components/latest/eips/routingSlip.html

Каждое сообщение несёт header ``routing_slip`` — список endpoint URI / processor
names, через которые message должен пройти. Порядок определяется runtime'ом
(per-message), что отличает от статического Pipeline.

Использование в DSL::

    from src.backend.dsl.engine.processors.eip.routing_slip import (
        RoutingSlipProcessor,
    )

    .set_header("routing_slip", ["audit", "transform_json", "send_to_s3"])
    .process(RoutingSlipProcessor(
        steps_resolver=lambda ex: ex.in_message.get_header("routing_slip"),
        registry=processor_registry,  # map name → processor instance
    ))

Или через DSL builder (S55 W1.2)::

    .routing_slip(header="routing_slip", registry=processor_registry)

Thread-safe: lock для current_index (по exchange не нужен — каждый exchange
имеет свой RoutingSlipContext через property).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, Protocol

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("ProcessorRegistry", "RoutingSlipProcessor", "SimpleRegistry")

_log = get_logger(__name__)


class ProcessorRegistry(Protocol):
    """Protocol для реестра processors (lookup by name)."""

    def get(self, name: str) -> BaseProcessor | None:
        """Возвращает processor по имени или None если не найден."""
        ...


class SimpleRegistry:
    """In-memory registry: name → processor. Thread-safe."""

    def __init__(self) -> None:
        self._processors: dict[str, BaseProcessor] = {}
        self._lock = threading.Lock()

    def register(self, name: str, processor: BaseProcessor) -> None:
        with self._lock:
            self._processors[name] = processor

    def unregister(self, name: str) -> None:
        with self._lock:
            self._processors.pop(name, None)

    def get(self, name: str) -> BaseProcessor | None:
        with self._lock:
            return self._processors.get(name)


# Type alias for steps resolver: given an exchange, returns the ordered
# list of step names to execute. May be sync or async.
StepsResolver = Callable[[Exchange[Any]], Any]


class RoutingSlipProcessor(BaseProcessor):
    """Динамическая цепочка processors per-message (Camel Routing Slip).

    На каждом exchange: резолвит список steps → выполняет их последовательно
    в текущем ExecutionContext. Если step не найден в registry — raises
    ``KeyError`` (можно отключить strict mode).

    State:
        ``exchange.set_property("routing_slip.remaining", [...])`` — оставшиеся
        steps (полезно для middleware / observability).

    Args:
        steps_resolver: Callable, возвращающий list[str] для данного exchange.
        registry: ProcessorRegistry для lookup по имени.
        strict: если True (default) — отсутствующий step → KeyError.
            Если False — warning + skip.
        max_steps: защита от бесконечной цепочки (default 50).
        name: имя процессора.
    """

    def __init__(
        self,
        steps_resolver: StepsResolver,
        registry: ProcessorRegistry,
        *,
        strict: bool = True,
        max_steps: int = 50,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "routing_slip")
        self._steps_resolver = steps_resolver
        self._registry = registry
        self._strict = strict
        self._max_steps = max_steps
        self._lock = threading.Lock()  # для shared stats

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        steps = self._steps_resolver(exchange)
        if asyncio.iscoroutine(steps):
            steps = await steps

        if not steps:
            _log.debug("RoutingSlip: no steps for exchange, skipping")
            return

        if len(steps) > self._max_steps:
            raise ValueError(
                f"RoutingSlip: {len(steps)} steps exceeds max_steps={self._max_steps}"
            )

        exchange.set_property("routing_slip.remaining", list(steps))
        exchange.set_property("routing_slip.total_steps", len(steps))

        for idx, step_name in enumerate(steps):
            processor = self._registry.get(step_name)
            if processor is None:
                msg = f"RoutingSlip: step {step_name!r} not found in registry"
                if self._strict:
                    raise KeyError(msg)
                _log.warning("%s — skipping", msg)
                continue

            _log.debug(
                "RoutingSlip[%d/%d]: executing %s", idx + 1, len(steps), step_name
            )
            await processor.process(exchange, context)
            exchange.set_property("routing_slip.remaining", list(steps[idx + 1 :]))
            exchange.set_property("routing_slip.current_step", step_name)

        _log.debug("RoutingSlip: completed all %d steps", len(steps))

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "routing_slip",
            "strict": self._strict,
            "max_steps": self._max_steps,
        }
