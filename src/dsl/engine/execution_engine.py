import time
from typing import Any

from src.core.state.runtime import disabled_feature_flags
from src.core.errors import RouteDisabledError
from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.dsl.engine.middleware import (
    ErrorNormalizerMiddleware,
    MetricsMiddleware,
    MiddlewareChain,
    TimeoutMiddleware,
)
from src.dsl.engine.pipeline import Pipeline
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.validation import pipeline_validator

__all__ = ("ExecutionEngine",)

_default_middleware = MiddlewareChain(
    [
        TimeoutMiddleware(default_timeout=30.0),
        ErrorNormalizerMiddleware(),
        MetricsMiddleware(),
    ]
)


class ExecutionEngine:
    """Исполнитель DSL-маршрутов с MiddlewareChain."""

    def __init__(
        self,
        middleware: MiddlewareChain | None = None,
        validate_before_execute: bool = True,
    ) -> None:
        self._middleware = middleware or _default_middleware
        self._validate = validate_before_execute
        self._timeout_mw = self._find_timeout_middleware()

    def _find_timeout_middleware(self) -> TimeoutMiddleware | None:
        for mw in self._middleware._middlewares:
            if isinstance(mw, TimeoutMiddleware):
                return mw
        return None

    @staticmethod
    def _check_feature_flag(pipeline: Pipeline) -> None:
        if (
            pipeline.feature_flag is not None
            and pipeline.feature_flag in disabled_feature_flags
        ):
            raise RouteDisabledError(
                route_id=pipeline.route_id, feature_flag=pipeline.feature_flag
            )

    async def _execute_processor(
        self,
        processor: BaseProcessor,
        exchange: Exchange[Any],
        context: ExecutionContext,
        route_id: str,
        tracer: Any,
    ) -> dict[str, Any]:
        """Выполняет один процессор, возвращает trace entry."""
        proc_start = time.monotonic()

        if context.logger is not None:
            context.logger.debug(
                "Executing '%s' for route '%s'", processor.name, route_id
            )

        timeout = (
            self._timeout_mw.get_timeout(processor.name) if self._timeout_mw else None
        )

        async with tracer.trace(route_id, processor.name, type(processor).__name__):
            await self._middleware.execute(
                processor, exchange, context, timeout=timeout
            )

        return {
            "processor": processor.name,
            "type": type(processor).__name__,
            "duration_ms": (time.monotonic() - proc_start) * 1000,
            "status": "ok",
        }

    @staticmethod
    def _finalize(exchange: Exchange[Any], pipeline: Pipeline, total_ms: float) -> None:
        """Set final exchange status and record SLO metrics."""
        if exchange.status != ExchangeStatus.failed:
            if exchange.out_message is None:
                exchange.complete(
                    body=exchange.in_message.body,
                    headers=dict(exchange.in_message.headers),
                )
            else:
                exchange.status = ExchangeStatus.completed

        try:
            from src.infrastructure.application.slo_tracker import get_slo_tracker

            get_slo_tracker().record(
                route_id=pipeline.route_id,
                latency_ms=total_ms,
                is_error=exchange.status == ExchangeStatus.failed,
            )
        except ImportError, AttributeError:
            pass

    async def execute(
        self,
        pipeline: Pipeline,
        *,
        exchange: Exchange[Any] | None = None,
        body: Any = None,
        headers: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
    ) -> Exchange[Any]:
        self._check_feature_flag(pipeline)

        if self._validate:
            result = pipeline_validator.validate(pipeline)
            if not result.valid:
                errors = "; ".join(i.message for i in result.errors)
                raise ValueError(
                    f"Pipeline '{pipeline.route_id}' validation failed: {errors}"
                )

        runtime_context = context or ExecutionContext()
        runtime_context.route_id = pipeline.route_id

        current_exchange = exchange or Exchange(
            in_message=Message(body=body, headers=headers or {})
        )
        current_exchange.meta.route_id = pipeline.route_id
        current_exchange.meta.source = pipeline.source
        current_exchange.status = ExchangeStatus.processing

        from src.dsl.engine.tracer import get_tracer

        tracer = get_tracer()
        trace_log: list[dict[str, Any]] = []
        pipeline_start = time.monotonic()

        for processor in pipeline.processors:
            if (
                current_exchange.status == ExchangeStatus.failed
                or current_exchange.stopped
            ):
                break

            try:
                entry = await self._execute_processor(
                    processor,
                    current_exchange,
                    runtime_context,
                    pipeline.route_id,
                    tracer,
                )
                trace_log.append(entry)
            except Exception as exc:
                duration_ms = (time.monotonic() - pipeline_start) * 1000
                if runtime_context.logger is not None:
                    runtime_context.logger.exception(
                        "Processor '%s' failed in route '%s'",
                        processor.name,
                        pipeline.route_id,
                    )
                trace_log.append(
                    {
                        "processor": processor.name,
                        "type": type(processor).__name__,
                        "duration_ms": duration_ms,
                        "status": "error",
                        "error": str(exc),
                    }
                )
                current_exchange.fail(str(exc))
                break

        current_exchange.set_property("_trace", trace_log)
        self._finalize(
            current_exchange, pipeline, (time.monotonic() - pipeline_start) * 1000
        )
        return current_exchange
