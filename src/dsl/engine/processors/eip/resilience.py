import asyncio
import logging
import time
from typing import Any

import orjson

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, ExchangeStatus
from src.dsl.engine.processors.base import BaseProcessor

_eip_logger = logging.getLogger("dsl.eip")
_camel_logger = logging.getLogger("dsl.camel")

__all__ = (
    "DeadLetterProcessor",
    "FallbackChainProcessor",
    "CircuitBreakerProcessor",
    "TimeoutProcessor",
)


class DeadLetterProcessor(BaseProcessor):
    """Dead Letter Channel — направляет упавшие Exchange в DLQ.

    Оборачивает sub-pipeline. При неуспехе сохраняет Exchange
    в DLQ-хранилище (Redis stream) с полным контекстом ошибки.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        dlq_stream: str = "dsl-dlq",
        max_retries: int = 0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "dead_letter")
        self._processors = processors
        self._dlq_stream = dlq_stream
        self._max_retries = max_retries

    async def _send_to_dlq(self, exchange: Exchange[Any]) -> None:
        try:
            from src.infrastructure.clients.storage.redis import redis_client

            dlq_entry = {
                "exchange_id": exchange.meta.exchange_id,
                "route_id": exchange.meta.route_id or "",
                "correlation_id": exchange.meta.correlation_id,
                "error": exchange.error or "unknown",
                "body": orjson.dumps(exchange.in_message.body, default=str).decode()[
                    :8192
                ]
                if exchange.in_message.body
                else "",
                "properties": orjson.dumps(exchange.properties, default=str).decode()[
                    :4096
                ],
                "timestamp": exchange.meta.created_at.isoformat(),
            }
            await redis_client.add_to_stream(
                stream_name=self._dlq_stream, data=dlq_entry
            )
            _eip_logger.info(
                "Exchange %s sent to DLQ stream '%s'",
                exchange.meta.exchange_id,
                self._dlq_stream,
            )
        except Exception as dlq_exc:
            _eip_logger.error("Failed to send to DLQ: %s", dlq_exc)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.dsl.engine.processors.base import run_sub_processors

        try:
            await run_sub_processors(self._processors, exchange, context)
        except Exception as exc:
            exchange.fail(str(exc))

        if exchange.status == ExchangeStatus.failed:
            await self._send_to_dlq(exchange)


class FallbackChainProcessor(BaseProcessor):
    """Fallback Chain — последовательно пробует процессоры.

    Выполняет первый процессор. При ошибке — следующий.
    Останавливается на первом успешном. Если все провалились —
    Exchange завершается ошибкой последнего.
    """

    def __init__(
        self, processors: list[BaseProcessor], *, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"fallback_chain({len(processors)})")
        self._processors = processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        last_error: str | None = None

        for i, proc in enumerate(self._processors):
            exchange.status = ExchangeStatus.processing
            exchange.error = None
            exchange.properties.pop("_stopped", None)

            try:
                await proc.process(exchange, context)
                if exchange.status != ExchangeStatus.failed:
                    exchange.set_property("fallback_used", i)
                    return
                last_error = exchange.error
            except Exception as exc:
                last_error = str(exc)
                _eip_logger.debug("Fallback %d (%s) failed: %s", i, proc.name, exc)

        exchange.fail(f"All fallbacks exhausted. Last error: {last_error}")


class CircuitBreakerProcessor(BaseProcessor):
    """Camel Circuit Breaker EIP — fail-fast pattern inside DSL pipeline.

    Wraps sub-processors with CLOSED → OPEN → HALF_OPEN state machine.
    When open, immediately routes to fallback or fails.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 1,
        fallback_processors: list[BaseProcessor] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"circuit_breaker(threshold={failure_threshold})")
        self._processors = processors
        self._fallback = fallback_processors or []
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max = half_open_max
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    def _check_state(self) -> str:
        if self._state == "open":
            if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                self._state = "half_open"
                self._half_open_calls = 0
        return self._state

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.dsl.engine.processors.base import run_sub_processors

        async with self._lock:
            state = self._check_state()

            if state == "open":
                if self._fallback:
                    exchange.set_property("cb_state", "open_fallback")
                    await run_sub_processors(self._fallback, exchange, context)
                    return
                exchange.fail("Circuit breaker is OPEN")
                return

            if state == "half_open":
                self._half_open_calls += 1
                if self._half_open_calls > self._half_open_max:
                    exchange.fail("Circuit breaker HALF_OPEN: max calls exceeded")
                    return

        await run_sub_processors(self._processors, exchange, context)

        async with self._lock:
            if exchange.status == ExchangeStatus.failed:
                self._failure_count += 1
                self._last_failure_time = time.monotonic()
                if self._failure_count >= self._threshold:
                    self._state = "open"
                exchange.set_property("cb_state", self._state)
            else:
                if self._state == "half_open":
                    self._state = "closed"
                self._failure_count = 0
                exchange.set_property("cb_state", self._state)


class TimeoutProcessor(BaseProcessor):
    """Camel Timeout EIP — wrap sub-processors with a time limit.

    If processing exceeds the timeout, the exchange is failed
    and an optional fallback is executed.

    Usage::

        .timeout(processors=[HttpCallProcessor(...)], seconds=10,
                 fallback=[LogProcessor()])
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        seconds: float = 30.0,
        fallback_processors: list[BaseProcessor] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"timeout({seconds}s)")
        self._processors = processors
        self._seconds = seconds
        self._fallback = fallback_processors or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.dsl.engine.processors.base import run_sub_processors

        try:
            await asyncio.wait_for(
                run_sub_processors(self._processors, exchange, context),
                timeout=self._seconds,
            )
        except asyncio.TimeoutError:
            exchange.set_property("timeout_exceeded", True)
            exchange.set_property("timeout_limit_seconds", self._seconds)

            if self._fallback:
                await run_sub_processors(self._fallback, exchange, context)
            else:
                exchange.fail(f"Timeout after {self._seconds}s")
