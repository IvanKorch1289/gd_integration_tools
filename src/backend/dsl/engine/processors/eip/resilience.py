import asyncio
import logging
from typing import Any

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.processors.base import BaseProcessor

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
            from src.backend.infrastructure.clients.storage.redis import redis_client

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
        from src.backend.dsl.engine.processors.base import run_sub_processors

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


class _SubPipelineFailure(Exception):
    """Внутренний сигнал: sub-pipeline завершился со статусом ``failed``.

    Поднимается внутри ``guard()`` purgatory-breaker'а, чтобы failure-counter
    зафиксировал отказ. Наружу из ``CircuitBreakerProcessor.process`` не
    пробрасывается — обрабатывается локально.
    """


class CircuitBreakerProcessor(BaseProcessor):
    """Camel Circuit Breaker EIP — fail-fast pattern inside DSL pipeline.

    Wave 26.7: делегирует state-machine в общий ``breaker_registry``
    (purgatory-based). Метрика ``infra_client_circuit_state`` публикуется
    автоматически. Локальное состояние не хранится — единый источник
    правды на процесс.

    Namespace в имени breaker'а:
        ``dsl.pipeline.<route_id>`` — если ``name`` не задан явно;
        ``dsl.<custom>`` — если передан ``name``.
    """

    _DSL_NAMESPACE = "dsl.pipeline"

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max: int = 1,
        fallback_processors: list[BaseProcessor] | None = None,
        name: str | None = None,
        breaker_name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"circuit_breaker(threshold={failure_threshold})")
        self._processors = processors
        self._fallback = fallback_processors or []
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        # half_open_max — параметр оставлен в публичной сигнатуре для
        # обратной совместимости; purgatory сам управляет half-open
        # пропуском (single trial), поэтому значение в делегированном
        # режиме не используется.
        self._half_open_max = half_open_max
        self._breaker_name_override = breaker_name

    def _resolve_breaker_name(self, exchange: Exchange[Any]) -> str:
        """Сформировать имя breaker'а с DSL-namespace."""
        if self._breaker_name_override:
            return self._breaker_name_override
        route_id = exchange.meta.route_id or "_anonymous"
        return f"{self._DSL_NAMESPACE}.{route_id}"

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.dsl.engine.processors.base import run_sub_processors
        from src.backend.infrastructure.resilience.breaker import (
            BreakerSpec,
            CircuitOpen,
            breaker_registry,
        )

        breaker_name = self._resolve_breaker_name(exchange)
        breaker = breaker_registry.get_or_create(
            breaker_name,
            BreakerSpec(
                failure_threshold=self._threshold,
                recovery_timeout=self._recovery_timeout,
            ),
            host="dsl",
        )

        try:
            async with breaker.guard():
                await run_sub_processors(self._processors, exchange, context)
                if exchange.status == ExchangeStatus.failed:
                    # Сигнализируем purgatory о неуспехе через исключение,
                    # чтобы failure-counter инкрементился корректно.
                    raise _SubPipelineFailure(exchange.error or "sub-pipeline failed")
        except CircuitOpen:
            if self._fallback:
                exchange.status = ExchangeStatus.processing
                exchange.error = None
                exchange.set_property("cb_state", "open_fallback")
                await run_sub_processors(self._fallback, exchange, context)
                return
            exchange.fail("Circuit breaker is OPEN")
            exchange.set_property("cb_state", "open")
            return
        except _SubPipelineFailure:
            # Sub-pipeline уже выставил ``exchange.fail(...)`` — не
            # перезаписываем error. purgatory зафиксировал failure.
            exchange.set_property("cb_state", breaker.state)
            return

        exchange.set_property("cb_state", breaker.state)


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
        from src.backend.dsl.engine.processors.base import run_sub_processors

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
