import asyncio
import logging
import time
from typing import Any, Callable

import orjson

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from app.dsl.engine.processors.base import BaseProcessor

_eip_logger = logging.getLogger("dsl.eip")
_camel_logger = logging.getLogger("dsl.camel")

__all__ = ('WireTapProcessor', 'ThrottlerProcessor', 'DelayProcessor', 'AggregatorProcessor', 'LoopProcessor', 'OnCompletionProcessor')


class WireTapProcessor(BaseProcessor):
    """Wire Tap — копирует Exchange в отдельный канал.

    Не влияет на основной поток. Полезно для логирования,
    аудита, отладки.

    Args:
        tap_processors: Процессоры, обрабатывающие копию Exchange.
    """

    def __init__(
        self,
        tap_processors: list[BaseProcessor],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "wire_tap")
        self._tap_processors = tap_processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        tap_exchange = Exchange(
            in_message=Message(
                body=exchange.in_message.body,
                headers=dict(exchange.in_message.headers),
            )
        )
        tap_exchange.meta.route_id = exchange.meta.route_id
        tap_exchange.meta.correlation_id = exchange.meta.correlation_id
        tap_exchange.properties = dict(exchange.properties)
        tap_exchange.status = ExchangeStatus.processing

        async def _run_tap() -> None:
            for proc in self._tap_processors:
                if tap_exchange.status == ExchangeStatus.failed:
                    break
                try:
                    await proc.process(tap_exchange, context)
                except Exception as exc:
                    _eip_logger.debug("Wire tap processor error: %s", exc)

        task = asyncio.create_task(_run_tap())
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


# ---------------------------------------------------------------------------
#  Apache Camel-inspired процессоры
# ---------------------------------------------------------------------------



class ThrottlerProcessor(BaseProcessor):
    """Rate-limit per route: N сообщений в секунду.

    Использует token bucket для контроля пропускной
    способности. При превышении — задержка.
    """

    def __init__(
        self,
        rate: float,
        *,
        burst: int = 1,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"throttle({rate}/s)")
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = 0.0
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time

        async with self._lock:
            now = time.monotonic()
            if self._last_refill == 0.0:
                self._last_refill = now

            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0



class DelayProcessor(BaseProcessor):
    """Задержка обработки на N миллисекунд или до timestamp."""

    def __init__(
        self,
        delay_ms: int | None = None,
        *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"delay({delay_ms}ms)")
        self._delay_ms = delay_ms
        self._scheduled_fn = scheduled_time_fn

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time

        if self._scheduled_fn is not None:
            target = self._scheduled_fn(exchange)
            now = time.time()
            if target > now:
                await asyncio.sleep(target - now)
        elif self._delay_ms is not None and self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000.0)



class AggregatorProcessor(BaseProcessor):
    """Собирает N Exchange по correlation_id.

    Накапливает результаты в shared state (context.state),
    выдаёт агрегированный результат по достижении ``batch_size``
    или ``timeout``.
    """

    _MAX_CORRELATION_KEYS = 10000

    def __init__(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
        max_buffer_size: int = 100000,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"aggregator(batch={batch_size})")
        self._corr_key = correlation_key
        self._batch_size = batch_size
        self._timeout = timeout_seconds
        self._max_buffer = max_buffer_size
        self._buffers: dict[str, list[Any]] = {}
        self._timestamps: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time
        key = self._corr_key(exchange)
        now = time.monotonic()

        async with self._lock:
            self._flush_expired(now)

            if len(self._buffers) >= self._MAX_CORRELATION_KEYS:
                oldest = next(iter(self._buffers))
                del self._buffers[oldest]
                self._timestamps.pop(oldest, None)

            buf = self._buffers.setdefault(key, [])
            self._timestamps.setdefault(key, now)
            if len(buf) >= self._max_buffer:
                buf.pop(0)
            buf.append(exchange.in_message.body)

            if len(buf) >= self._batch_size:
                aggregated = list(buf)
                buf.clear()
                self._timestamps.pop(key, None)
                exchange.set_property("aggregated", True)
                exchange.set_out(body=aggregated, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property("aggregated", False)
                exchange.set_property("buffer_size", len(buf))
                exchange.stop()

    def _flush_expired(self, now: float) -> None:
        """Remove buffers that exceeded timeout to prevent memory leaks."""
        expired = [k for k, ts in self._timestamps.items() if now - ts > self._timeout]
        for k in expired:
            self._buffers.pop(k, None)
            self._timestamps.pop(k, None)



class LoopProcessor(BaseProcessor):
    """Camel Loop EIP — execute sub-processors N times or until condition.

    Supports fixed count, do-while (condition checked after each iteration),
    and while (condition checked before). Each iteration receives the previous
    result as input body.

    Usage::

        .loop(processors=[...], count=5)
        .loop(processors=[...], until=lambda ex: ex.in_message.body.get("done"))
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        count: int | None = None,
        until: Callable[[Exchange[Any]], bool] | None = None,
        max_iterations: int = 1000,
        copy_exchange: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"loop({count or 'until'})")
        self._processors = processors
        self._count = count
        self._until = until
        self._max_iterations = max_iterations
        self._copy = copy_exchange

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.dsl.engine.processors.base import run_sub_processors

        iteration = 0
        results: list[Any] = []

        while iteration < self._max_iterations:
            if self._count is not None and iteration >= self._count:
                break

            if self._until is not None and iteration > 0:
                try:
                    if self._until(exchange):
                        break
                except Exception:
                    break

            exchange.set_property("loop_index", iteration)
            exchange.set_property("loop_size", self._count or -1)

            if exchange.status == ExchangeStatus.failed or exchange.stopped:
                break

            await run_sub_processors(self._processors, exchange, context)

            result = (
                exchange.out_message.body
                if exchange.out_message
                else exchange.in_message.body
            )
            results.append(result)

            if exchange.out_message:
                exchange.in_message = Message(
                    body=exchange.out_message.body,
                    headers=dict(exchange.out_message.headers),
                )
                exchange.out_message = None

            iteration += 1

        exchange.set_property("loop_count", iteration)
        exchange.set_property("loop_results", results)



class OnCompletionProcessor(BaseProcessor):
    """Camel OnCompletion EIP — execute callback processors after pipeline completes.

    Runs regardless of success or failure (like finally).
    Can be filtered to run only on success or only on failure.

    Usage::

        .on_completion(
            processors=[LogProcessor(), NotifyProcessor(...)],
            on_failure_only=True,
        )
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        on_success_only: bool = False,
        on_failure_only: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "on_completion")
        self._processors = processors
        self._on_success = on_success_only
        self._on_failure = on_failure_only

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        is_failed = exchange.status == ExchangeStatus.failed

        if self._on_success and is_failed:
            return
        if self._on_failure and not is_failed:
            return

        saved_status = exchange.status
        saved_error = exchange.error

        for proc in self._processors:
            try:
                await proc.process(exchange, context)
            except Exception as exc:
                _camel_logger.warning("OnCompletion processor error: %s", exc)

        exchange.status = saved_status
        exchange.error = saved_error


