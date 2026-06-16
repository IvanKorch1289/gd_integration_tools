import time
from typing import Any

from src.backend.core.errors import RouteDisabledError, TenantContextRequiredError
from src.backend.core.state.runtime import disabled_feature_flags
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.middleware import (
    ErrorNormalizerMiddleware,
    MetricsMiddleware,
    MiddlewareChain,
    TimeoutMiddleware,
)
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processor_pool import ProcessorPool, get_processor_pool
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.validation import pipeline_validator

__all__ = ("ExecutionEngine",)


def _resolve_tenant_id() -> str | None:
    """Резолвит tenant_id из RequestContext или TenantContext.

    K-ARCH-4 (S17): pipeline.tenant_aware=True требует хотя бы один из
    источников. Порядок приоритета:

    1. :class:`src.backend.core.request_context.RequestContext` →
       ``.tenant_id`` (устанавливается RequestContextMiddleware рано
       в ASGI-цепочке).
    2. :func:`src.backend.core.tenancy.current_tenant` →
       ``TenantContext.tenant_id`` (устанавливается TenantMiddleware
       или явно в background-задачах).

    Returns:
        Найденный непустой tenant_id или ``None``.
    """
    from src.backend.core.request_context import RequestContext
    from src.backend.core.tenancy import current_tenant

    ctx = RequestContext.current()
    if ctx is not None and ctx.tenant_id:
        return ctx.tenant_id

    tenant_ctx = current_tenant()
    if tenant_ctx is not None and tenant_ctx.tenant_id:
        return tenant_ctx.tenant_id
    return None


def _default_middleware_factory() -> MiddlewareChain:
    """Factory for default middleware chain (avoids mutable default)."""
    return MiddlewareChain(
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
        pool: ProcessorPool | None = None,
    ) -> None:
        self._middleware = middleware or _default_middleware_factory()
        self._validate = validate_before_execute
        self._pool = pool or get_processor_pool()
        self._validation_cache: dict[str, Any] = {}

    @staticmethod
    def _find_timeout_middleware_in(chain: MiddlewareChain) -> TimeoutMiddleware | None:
        for mw in chain.iter_middlewares():
            if isinstance(mw, TimeoutMiddleware):
                return mw
        return None

    def _build_chain(self, pipeline: Pipeline) -> MiddlewareChain:
        """Собирает effective middleware chain для pipeline.

        Route-specific middleware заменяет default middleware того же класса;
        middleware'ы уникальных классов добавляются после defaults.
        """
        defaults = list(self._middleware.iter_middlewares())
        route = list(pipeline.middlewares)
        result: list[Any] = []
        used: list[bool] = [False] * len(route)

        for default in defaults:
            replacement: Any | None = None
            for i, rm in enumerate(route):
                if not used[i] and type(rm) is type(default):
                    replacement = rm
                    used[i] = True
                    break
            result.append(replacement if replacement is not None else default)

        for i, rm in enumerate(route):
            if not used[i]:
                result.append(rm)

        return MiddlewareChain(result)

    def _cached_validate(self, pipeline: Pipeline) -> Any:
        """Validate pipeline with LRU-style cache by route_id."""
        key = pipeline.route_id
        cached = self._validation_cache.get(key)
        if cached is not None:
            return cached
        result = pipeline_validator.validate(pipeline)
        self._validation_cache[key] = result
        return result

    @property
    def pool(self) -> ProcessorPool:
        """Returns the processor pool used by this engine."""
        return self._pool

    @staticmethod
    def _check_feature_flag(pipeline: Pipeline) -> None:
        if (
            pipeline.feature_flag is not None
            and pipeline.feature_flag in disabled_feature_flags
        ):
            raise RouteDisabledError(
                route_id=pipeline.route_id, feature_flag=pipeline.feature_flag
            )

    @staticmethod
    def _check_tenant_aware(pipeline: Pipeline) -> str | None:
        """Проверка K-ARCH-4: tenant_aware → tenant_id обязателен.

        Returns:
            Найденный tenant_id (если pipeline.tenant_aware=True) или
            ``None`` (если pipeline.tenant_aware=False).

        Raises:
            TenantContextRequiredError: pipeline.tenant_aware=True, но
                ни RequestContext.tenant_id, ни current_tenant() не
                содержат непустой tenant_id.
        """
        if not pipeline.tenant_aware:
            return None
        tenant_id = _resolve_tenant_id()
        if not tenant_id:
            raise TenantContextRequiredError(route_id=pipeline.route_id)
        return tenant_id

    async def _execute_processor(
        self,
        processor: BaseProcessor,
        exchange: Exchange[Any],
        context: ExecutionContext,
        route_id: str,
        tracer: Any,
        middleware_chain: MiddlewareChain,
        timeout_mw: TimeoutMiddleware | None,
    ) -> dict[str, Any]:
        """Выполняет один процессор, возвращает trace entry."""
        proc_start = time.monotonic()

        if context.logger is not None:
            context.logger.debug(
                "Executing '%s' for route '%s'", processor.name, route_id
            )

        timeout = timeout_mw.get_timeout(processor.name) if timeout_mw else None

        async with tracer.trace(route_id, processor.name, type(processor).__name__):
            await middleware_chain.execute(
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
            from src.backend.infrastructure.application.slo_tracker import (
                get_slo_tracker,
            )

            get_slo_tracker().record(
                route_id=pipeline.route_id,
                latency_ms=total_ms,
                is_error=exchange.status == ExchangeStatus.failed,
            )
        except (ImportError, AttributeError):
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
        tenant_id = self._check_tenant_aware(pipeline)

        if self._validate:
            result = self._cached_validate(pipeline)
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
        if tenant_id is not None:
            current_exchange.meta.tenant_id = tenant_id
            current_exchange.properties.setdefault("tenant_id", tenant_id)

        from src.backend.dsl.engine.tracer import get_tracer

        tracer = get_tracer()
        trace_log: list[dict[str, Any]] = []
        pipeline_start = time.monotonic()

        middleware_chain = self._build_chain(pipeline)
        timeout_mw = self._find_timeout_middleware_in(middleware_chain)

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
                    middleware_chain,
                    timeout_mw,
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

    async def execute_parallel(
        self,
        processors: list[BaseProcessor],
        *,
        exchange: Exchange[Any] | None = None,
        body: Any = None,
        headers: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
        pipeline: Pipeline | None = None,
    ) -> Exchange[Any]:
        """Execute multiple processors in parallel using the processor pool.

        Args:
            processors: List of processors to execute.
            exchange: Optional existing exchange.
            body: Request body.
            headers: Request headers.
            context: Optional execution context.
            pipeline: Optional pipeline for feature-flag and tenant checks.

        Returns:
            Exchange with results from all processors.
        """
        if pipeline is not None:
            self._check_feature_flag(pipeline)
            self._check_tenant_aware(pipeline)

        current_exchange = exchange or Exchange(
            in_message=Message(body=body, headers=headers or {})
        )
        runtime_context = context or ExecutionContext()

        trace_log = await self._pool.execute_parallel(
            processors, current_exchange, runtime_context
        )

        current_exchange.set_property("_trace", trace_log)

        if any(entry.get("status") == "error" for entry in trace_log):
            errors = [
                e.get("error", "Unknown")
                for e in trace_log
                if e.get("status") == "error"
            ]
            current_exchange.fail("; ".join(errors))
        else:
            current_exchange.status = ExchangeStatus.completed

        return current_exchange
