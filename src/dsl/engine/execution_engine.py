import time
from typing import Any

from app.core.config.runtime_state import disabled_feature_flags
from app.core.errors import RouteDisabledError
from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from app.dsl.engine.middleware import (
    ErrorNormalizerMiddleware,
    MetricsMiddleware,
    MiddlewareChain,
    TimeoutMiddleware,
)
from app.dsl.engine.pipeline import Pipeline
from app.dsl.engine.validation import pipeline_validator

__all__ = ("ExecutionEngine",)

_default_middleware = MiddlewareChain([
    TimeoutMiddleware(default_timeout=30.0),
    ErrorNormalizerMiddleware(),
    MetricsMiddleware(),
])


class ExecutionEngine:
    """Исполнитель DSL-маршрутов с MiddlewareChain.

    Middleware обеспечивает:
    - Per-processor timeout enforcement
    - Error normalization (единый формат ошибок)
    - Metrics collection (latency, success/error per processor)
    - Pipeline validation перед выполнением
    """

    def __init__(
        self,
        middleware: MiddlewareChain | None = None,
        validate_before_execute: bool = True,
    ) -> None:
        self._middleware = middleware or _default_middleware
        self._validate = validate_before_execute

    @staticmethod
    def _check_feature_flag(pipeline: Pipeline) -> None:
        if (
            pipeline.feature_flag is not None
            and pipeline.feature_flag in disabled_feature_flags
        ):
            raise RouteDisabledError(
                route_id=pipeline.route_id,
                feature_flag=pipeline.feature_flag,
            )

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
                raise ValueError(f"Pipeline '{pipeline.route_id}' validation failed: {errors}")

        runtime_context = context or ExecutionContext()
        runtime_context.route_id = pipeline.route_id

        current_exchange = exchange or Exchange(
            in_message=Message(body=body, headers=headers or {})
        )
        current_exchange.meta.route_id = pipeline.route_id
        current_exchange.meta.source = pipeline.source
        current_exchange.status = ExchangeStatus.processing

        from app.dsl.engine.tracer import get_tracer

        tracer = get_tracer()
        trace_log: list[dict[str, Any]] = []
        pipeline_start = time.monotonic()

        for processor in pipeline.processors:
            if current_exchange.status == ExchangeStatus.failed:
                break
            if current_exchange.stopped:
                break

            proc_start = time.monotonic()

            try:
                if runtime_context.logger is not None:
                    runtime_context.logger.debug(
                        "Executing '%s' for route '%s'",
                        processor.name, pipeline.route_id,
                    )

                timeout = None
                for mw in self._middleware._middlewares:
                    if isinstance(mw, TimeoutMiddleware):
                        timeout = mw.get_timeout(processor.name)
                        break

                async with tracer.trace(
                    pipeline.route_id, processor.name, type(processor).__name__
                ) as trace_data:
                    await self._middleware.execute(
                        processor, current_exchange, runtime_context,
                        timeout=timeout,
                    )

                duration_ms = (time.monotonic() - proc_start) * 1000
                trace_log.append({
                    "processor": processor.name,
                    "type": type(processor).__name__,
                    "duration_ms": duration_ms,
                    "status": "ok",
                })

            except Exception as exc:
                duration_ms = (time.monotonic() - proc_start) * 1000

                if runtime_context.logger is not None:
                    runtime_context.logger.exception(
                        "Processor '%s' failed in route '%s'",
                        processor.name, pipeline.route_id,
                    )

                trace_log.append({
                    "processor": processor.name,
                    "type": type(processor).__name__,
                    "duration_ms": duration_ms,
                    "status": "error",
                    "error": str(exc),
                })
                current_exchange.fail(str(exc))
                break

        current_exchange.set_property("_trace", trace_log)

        if current_exchange.status != ExchangeStatus.failed:
            if current_exchange.out_message is None:
                current_exchange.complete(
                    body=current_exchange.in_message.body,
                    headers=dict(current_exchange.in_message.headers),
                )
            else:
                current_exchange.status = ExchangeStatus.completed

        total_ms = (time.monotonic() - pipeline_start) * 1000
        try:
            from app.infrastructure.application.slo_tracker import get_slo_tracker
            get_slo_tracker().record(
                route_id=pipeline.route_id,
                latency_ms=total_ms,
                is_error=current_exchange.status == ExchangeStatus.failed,
            )
        except Exception:
            pass

        return current_exchange
