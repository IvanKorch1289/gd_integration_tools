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
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, run_sub_processors

__all__ = (
    "BatchWindowProcessor",
    "DebounceProcessor",
    "DeduplicateProcessor",
    "FormatterProcessor",
    "MergeProcessor",
    "SwitchProcessor",
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
        exchange.set_property(
            "switch_matched", key if key in self._cases else "default"
        )
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
        self, properties: list[str], *, mode: str = "append", name: str | None = None
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
            exchange.set_out(
                body=list(zip(*lists, strict=False)),
                headers=dict(exchange.in_message.headers),
            )
        else:
            exchange.set_out(body=values, headers=dict(exchange.in_message.headers))


try:  # pragma: no cover - prometheus_client опционален в dev_light
    from prometheus_client import Counter as _PromCounter

    _BATCH_FLUSH_COUNTER = _PromCounter(
        "dsl_batch_flushes_total",
        "Total number of BatchWindow flushes",
        ("reason", "group"),
    )
except Exception as _:
    _BATCH_FLUSH_COUNTER = None  # type: ignore[assignment,unused-ignore]


def _record_batch_flush(reason: str, group: str = "_global") -> None:
    """Записать flush-метрику; no-op если prometheus_client недоступен."""
    if _BATCH_FLUSH_COUNTER is None:
        return
    with contextlib.suppress(Exception):
        _BATCH_FLUSH_COUNTER.labels(reason=reason, group=group).inc()


class BatchWindowProcessor(BaseProcessor):
    """Benthos-style time-window batching c опциональной группировкой (S13 K3 W1).

    Собирает сообщения в окно по времени ИЛИ размеру. С ``group_by`` flush
    выполняется per-group: разные correlation-keys собирают независимые окна.

    Usage::

        .batch(size=100, timeout_ms=500)  # глобальный буфер
        .batch(size=50, timeout_ms=1000, group_by="header.tenant_id")  # per-tenant
    """

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        max_size: int = 100,
        group_by: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            name=name
            or f"batch_window({window_seconds}s, {max_size}, group_by={group_by})"
        )
        self._window = window_seconds
        self._max_size = max_size
        self._group_by = group_by
        self._buffers: dict[str, list[Any]] = {}
        self._window_starts: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _resolve_group(self, exchange: Exchange[Any]) -> str:
        if not self._group_by:
            return "_global"
        path = self._group_by
        body = exchange.in_message.body
        headers = exchange.in_message.headers
        if path.startswith("header."):
            return str(headers.get(path[len("header.") :], "_default"))
        if path.startswith("body.") and isinstance(body, dict):
            key = path[len("body.") :]
            return str(body.get(key, "_default"))
        if path.startswith("property."):
            return str(exchange.properties.get(path[len("property.") :], "_default"))
        return "_default"

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        group = self._resolve_group(exchange)
        async with self._lock:
            now = time.monotonic()
            buffer = self._buffers.setdefault(group, [])
            if self._window_starts.get(group, 0.0) == 0.0:
                self._window_starts[group] = now

            buffer.append(exchange.in_message.body)

            size_reached = len(buffer) >= self._max_size
            timeout_reached = (now - self._window_starts[group]) >= self._window

            if size_reached or timeout_reached:
                batch = list(buffer)
                buffer.clear()
                self._window_starts[group] = 0.0
                reason = "size_reached" if size_reached else "timeout_reached"
                _record_batch_flush(reason, group)
                exchange.set_property("batch_size", len(batch))
                exchange.set_property("batch_group", group)
                exchange.set_property("batch_flush_reason", reason)
                exchange.set_out(body=batch, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property("batched", False)
                exchange.set_property("buffer_size", len(buffer))
                exchange.set_property("batch_group", group)
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

    def __init__(
        self,
        template: str,
        *,
        output_property: str | None = None,
        name: str | None = None,
    ) -> None:
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
            expired = [
                k for k, ts in self._last_seen.items() if now - ts > self._delay * 10
            ]
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
