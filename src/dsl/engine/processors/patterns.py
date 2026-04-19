"""Patterns from popular integration frameworks (n8n, Benthos, Zapier).

Processors added:
- SwitchProcessor (n8n Switch node): case/match routing
- MergeProcessor (n8n Merge node): combine N properties into body
- BatchWindowProcessor (Benthos): time-window batching
- DeduplicateProcessor (Benthos): dedup within time window
- FormatterProcessor (Zapier): string formatting from properties
- DebounceProcessor (Zapier): group repeated events, keep last only
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from app.dsl.engine.processors.base import BaseProcessor, run_sub_processors

__all__ = (
    "SwitchProcessor",
    "MergeProcessor",
    "BatchWindowProcessor",
    "DeduplicateProcessor",
    "FormatterProcessor",
    "DebounceProcessor",
)

_patterns_logger = logging.getLogger("dsl.patterns")


class SwitchProcessor(BaseProcessor):
    """n8n Switch node — маршрутизация по значению поля.

    Проще чем Choice: берёт значение поля из body и ищет его в cases.
    Если значение не найдено — выполняет default.

    Usage::

        .switch("status", cases={
            "pending": [SetHeaderProcessor("x-route", "pending")],
            "active": [DispatchActionProcessor("orders.process")],
        }, default=[LogProcessor()])
    """

    def __init__(
        self,
        field: str,
        cases: dict[str, list[BaseProcessor]],
        *,
        default: list[BaseProcessor] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"switch:{field}")
        self._field = field
        self._cases = cases
        self._default = default or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        value = None
        if isinstance(body, dict):
            value = body.get(self._field)

        key = str(value) if value is not None else ""
        branch = self._cases.get(key, self._default)
        exchange.set_property("switch_matched", key if key in self._cases else "default")
        await run_sub_processors(branch, exchange, context)


class MergeProcessor(BaseProcessor):
    """n8n Merge node — объединяет несколько properties в body.

    Режимы:
    - "append": body = [prop1, prop2, ...]
    - "merge": body = {**prop1, **prop2, ...} (для dict)
    - "zip": body = list of tuples из значений

    Usage::

        .merge(properties=["orders_data", "users_data"], mode="merge")
    """

    def __init__(
        self,
        properties: list[str],
        *,
        mode: str = "append",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"merge({mode})")
        self._properties = properties
        self._mode = mode

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        values = [exchange.properties.get(p) for p in self._properties]

        if self._mode == "merge":
            result: dict[str, Any] = {}
            for v in values:
                if isinstance(v, dict):
                    result.update(v)
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
        elif self._mode == "zip":
            lists = [v if isinstance(v, list) else [v] for v in values]
            exchange.set_out(body=list(zip(*lists)), headers=dict(exchange.in_message.headers))
        else:
            exchange.set_out(body=values, headers=dict(exchange.in_message.headers))


class BatchWindowProcessor(BaseProcessor):
    """Benthos-style time-window batching.

    Собирает сообщения в окно по времени ИЛИ размеру.
    Отличается от Aggregator: без correlation_key — общий буфер.

    Usage::

        .batch_window(window_seconds=60, max_size=100)
    """

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        max_size: int = 100,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"batch_window({window_seconds}s, {max_size})")
        self._window = window_seconds
        self._max_size = max_size
        self._buffer: list[Any] = []
        self._window_start: float = 0.0
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._window_start == 0.0:
                self._window_start = now

            self._buffer.append(exchange.in_message.body)

            should_flush = (
                len(self._buffer) >= self._max_size
                or (now - self._window_start) >= self._window
            )

            if should_flush:
                batch = list(self._buffer)
                self._buffer.clear()
                self._window_start = 0.0
                exchange.set_property("batch_size", len(batch))
                exchange.set_out(body=batch, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property("batched", False)
                exchange.set_property("buffer_size", len(self._buffer))
                exchange.stop()


class DeduplicateProcessor(BaseProcessor):
    """Benthos-style dedup в скользящем окне.

    Отличается от IdempotentConsumer: дедупликация только в окне,
    после окна тот же ключ снова проходит.

    Usage::

        .deduplicate(key_fn=lambda ex: ex.in_message.body.get("id"), window_seconds=60)
    """

    def __init__(
        self,
        key_fn: Callable[[Exchange[Any]], str],
        *,
        window_seconds: float = 60.0,
        max_keys: int = 10000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"deduplicate({window_seconds}s)")
        self._key_fn = key_fn
        self._window = window_seconds
        self._max_keys = max_keys
        self._seen: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = self._key_fn(exchange)
        now = time.monotonic()

        async with self._lock:
            expired = [k for k, ts in self._seen.items() if now - ts > self._window]
            for k in expired:
                del self._seen[k]

            if len(self._seen) >= self._max_keys:
                oldest = min(self._seen, key=self._seen.get)
                del self._seen[oldest]

            if key in self._seen:
                exchange.set_property("deduplicated", True)
                exchange.stop()
                return

            self._seen[key] = now
            exchange.set_property("deduplicated", False)


class FormatterProcessor(BaseProcessor):
    """Zapier Formatter — форматирует строку из body и properties.

    Template использует {field} для подстановки из body (dict)
    или {_property_name} для подстановки из exchange.properties.

    Usage::

        .format_text("Order {order_id} from {_user_email}")
    """

    def __init__(self, template: str, *, output_property: str | None = None, name: str | None = None) -> None:
        super().__init__(name=name or f"format_text:{template[:30]}")
        self._template = template
        self._output_property = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        variables: dict[str, Any] = {}
        if isinstance(body, dict):
            variables.update(body)
        for key, value in exchange.properties.items():
            if not key.startswith("_"):
                variables[key] = value
            else:
                variables[key] = value

        try:
            result = self._template.format_map(_SafeDict(variables))
        except (KeyError, ValueError, IndexError) as exc:
            exchange.fail(f"FormatterProcessor failed: {exc}")
            return

        if self._output_property:
            exchange.set_property(self._output_property, result)
        else:
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class _SafeDict(dict):
    """Dict that returns empty string for missing keys in format_map."""

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


class DebounceProcessor(BaseProcessor):
    """Zapier Debounce — группирует повторы, пропускает только последний.

    Если за delay_seconds пришло новое событие с тем же ключом —
    сбрасывает таймер. Через delay_seconds без новых — пропускает.

    Usage::

        .debounce(key_fn=lambda ex: ex.in_message.body.get("user_id"), delay_seconds=5)
    """

    def __init__(
        self,
        key_fn: Callable[[Exchange[Any]], str],
        *,
        delay_seconds: float = 5.0,
        max_keys: int = 10000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"debounce({delay_seconds}s)")
        self._key_fn = key_fn
        self._delay = delay_seconds
        self._max_keys = max_keys
        self._last_seen: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = self._key_fn(exchange)
        now = time.monotonic()

        async with self._lock:
            expired = [k for k, ts in self._last_seen.items() if now - ts > self._delay * 10]
            for k in expired:
                del self._last_seen[k]

            if len(self._last_seen) >= self._max_keys:
                oldest = min(self._last_seen, key=self._last_seen.get)
                del self._last_seen[oldest]

            last = self._last_seen.get(key, 0.0)
            self._last_seen[key] = now

            if now - last < self._delay:
                exchange.set_property("debounced", True)
                exchange.stop()
                return

            exchange.set_property("debounced", False)
