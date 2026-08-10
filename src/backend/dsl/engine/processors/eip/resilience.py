import asyncio
from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

_eip_logger = get_logger("dsl.eip")
_camel_logger = get_logger("dsl.camel")

__all__ = (
    "CircuitBreakerProcessor",
    "DeadLetterProcessor",
    "FallbackChainProcessor",
    "TimeoutProcessor",
)


@processor(
    "dead_letter",
    namespace="core",
    spec_schema={
        "type": "object",
        "description": "Camel Dead Letter Channel — wrap sub-pipeline и DLQ-route.",
        "properties": {
            "dlq_stream": {
                "type": "string",
                "default": "dsl-dlq",
                "description": "Redis stream name для DLQ записей.",
            },
            "dlq_path": {
                "type": ["string", "null"],
                "description": "Опциональный локальный JSONL fallback path.",
            },
            "max_retries": {"type": "integer", "minimum": 0, "default": 0},
            "name": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "description": "Exchange с DLQ entry в Redis stream (при failure); "
        "иначе passthrough.",
    },
    capabilities=("dsl.eip.dead_letter", "dsl.dlq.write"),
    tags=("eip", "reliability", "dlq"),
)
class DeadLetterProcessor(BaseProcessor):
    """Dead Letter Channel — направляет упавшие Exchange в DLQ.

    Оборачивает sub-pipeline. При неуспехе сохраняет Exchange
    в DLQ-хранилище (Redis stream) с полным контекстом ошибки.

    B-04 fix (cycle 38): registered через ``@processor`` декоратор —
    ``core:dead_letter``. Spec покрывает DLQ-target + max_retries.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        dlq_stream: str = "dsl-dlq",
        dlq_path: str | None = None,
        max_retries: int = 0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "dead_letter")
        self._processors = processors
        self._dlq_stream = dlq_stream
        self._dlq_path = dlq_path
        self._max_retries = max_retries

    async def _send_to_dlq(self, exchange: Exchange[Any]) -> None:
        """B-06 fix (cycle 33): 3-stage DLQ fallback (Redis → JSONL → metric+raise).

        Stage 1: ``redis_client.add_to_stream(self._dlq_stream, dlq_entry)``
            — primary hot-path DLQ (Redis stream).
        Stage 2: локальный JSONL через :class:`JsonlAuditBackend` — capability
            ``dsl.dlq.jsonl`` подключается по ``self._dlq_path`` (если
            сконфигурирован). Резолвится через ``importlib`` чтобы
            ``dsl/engine/`` не зависел от ``infrastructure/`` напрямую
            (см. layer-rules в :file:`tools/checks/check_layers.py`).
        Stage 3: терминальный отказ — инкремент :data:`dlq_send_failed_total`
            (метка ``stage="primary"|"all"``), ``_eip_logger.critical`` и
            raise :class:`RuntimeError`. Никогда silent loss.

        B-06: silent failure на DLQ-of-DLQ = P0-data-loss. Метрика позволяет
        алертингу отловить полную потерю записи (Redis down + JSONL down или
        недоступен). Референсный паттерн: services/audit/clickhouse_audit_service
        /service.py:159-219.
        """
        dlq_entry = {
            "exchange_id": exchange.meta.exchange_id,
            "route_id": exchange.meta.route_id or "",
            "correlation_id": exchange.meta.correlation_id,
            "error": exchange.error or "unknown",
            "body": orjson.dumps(exchange.in_message.body, default=str).decode()[:8192]
            if exchange.in_message.body
            else "",
            "properties": orjson.dumps(exchange.properties, default=str).decode()[
                :4096
            ],
            "timestamp": exchange.meta.created_at.isoformat(),
        }

        # ── Stage 1: Redis stream (primary) ──────────────────────────────
        try:
            from src.backend.infrastructure.clients.storage.redis import (
                redis_client as _redis_client,
            )

            await _redis_client.add_to_stream(
                stream_name=self._dlq_stream, data=dlq_entry,
            )
            _eip_logger.info(
                "Exchange %s sent to DLQ stream '%s' (stage=redis)",
                exchange.meta.exchange_id,
                self._dlq_stream,
            )
            return
        except Exception as stage1_exc:
            stage1_error: BaseException = stage1_exc

        # ── Stage 2: local JSONL fallback (capability-gated via dlq_path) ─
        stage2_error: BaseException | None = None
        if self._dlq_path:
            try:
                # B-11 follow-up (cycle 33): use capability-checked facade
                # instead of raw importlib (FAIL-2 Phase-5 ревью).
                from src.backend.core.audit.facade import get_jsonl_backend
                from src.backend.core.interfaces.audit import AuditRecord

                _backend = get_jsonl_backend(self._dlq_path)
                _record = AuditRecord(
                    {
                        "event": "dsl.dlq",
                        "action": "dlq_send_fallback_jsonl",
                        "entity_id": exchange.meta.exchange_id,
                        "after": dlq_entry,
                        "metadata": {
                            "dlq_reason": "redis_unavailable",
                            "stage1_error": repr(stage1_error),
                        },
                    },
                )
                await _backend.append(_record)
                _eip_logger.warning(
                    "Exchange %s DLQ stage1 (redis) failed, written to JSONL "
                    "'%s' (stage=jsonl): %s",
                    exchange.meta.exchange_id,
                    self._dlq_path,
                    stage1_error,
                )
                return
            except Exception as stage2_exc:
                stage2_error = stage2_exc

        # ── Stage 3: terminal — metric + critical log + raise ────────────
        from src.backend.core.observability.metrics import dlq_send_failed_total

        stage_label = "all" if self._dlq_path and stage2_error else "primary"
        dlq_send_failed_total.labels(stage=stage_label).inc()
        _eip_logger.critical(
            "DLQ send failed for exchange %s (stage=%s). stage1=%r "
            "stage2=%r dlq_path=%s",
            exchange.meta.exchange_id,
            stage_label,
            stage1_error,
            stage2_error,
            self._dlq_path,
        )
        raise RuntimeError(
            f"DLQ send failed for exchange {exchange.meta.exchange_id}: "
            f"redis={stage1_error!r}, jsonl="
            f"{(stage2_error if stage2_error else 'not_configured')!r}",
        ) from stage1_error

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        from src.backend.dsl.engine.processors.base import run_sub_processors

        try:
            await run_sub_processors(self._processors, exchange, context)
        except Exception as exc:
            exchange.fail(str(exc))

        if exchange.status == ExchangeStatus.failed:
            await self._send_to_dlq(exchange)


@processor(
    "fallback_chain",
    namespace="core",
    spec_schema={
        "type": "object",
        "description": "Camel Fallback Chain — sequential try-until-success.",
        "properties": {"name": {"type": "string"}},
    },
    output_schema={
        "type": "object",
        "description": "Exchange от первого успешного процессора; при exhausted — failed.",
    },
    capabilities=("dsl.eip.fallback_chain",),
    tags=("eip", "resilience", "fallback"),
)
class FallbackChainProcessor(BaseProcessor):
    """Fallback Chain — последовательно пробует процессоры.

    Выполняет первый процессор. При ошибке — следующий.
    Останавливается на первом успешном. Если все провалились —
    Exchange завершается ошибкой последнего.

    B-04 fix (cycle 38): registered через ``@processor`` декоратор —
    ``core:fallback_chain``.
    """

    def __init__(
        self, processors: list[BaseProcessor], *, name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"fallback_chain({len(processors)})")
        self._processors = processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
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


@processor(
    "circuit_breaker",
    namespace="core",
    spec_schema={
        "type": "object",
        "description": "Camel Circuit Breaker — fail-fast guard с fallback.",
        "properties": {
            "failure_threshold": {
                "type": "integer",
                "minimum": 1,
                "default": 5,
                "description": "Сколько failures до open state.",
            },
            "recovery_timeout": {
                "type": "number",
                "minimum": 0,
                "default": 30.0,
                "description": "Секунд до half-open trial.",
            },
            "half_open_max": {
                "type": "integer",
                "minimum": 1,
                "default": 1,
                "description": "(Deprecated) оставлен для обратной совместимости.",
            },
            "breaker_name": {
                "type": "string",
                "description": "Override имени breaker'а (default: dsl.pipeline.<route_id>).",
            },
            "name": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "description": "Exchange с property ``cb_state`` (open/closed/half_open/open_fallback).",
    },
    capabilities=("dsl.eip.circuit_breaker",),
    tags=("eip", "resilience", "circuit_breaker", "purgatory"),
)
class CircuitBreakerProcessor(BaseProcessor):
    """Camel Circuit Breaker EIP — fail-fast pattern inside DSL pipeline.

    Wave 26.7: делегирует state-machine в общий ``breaker_registry``
    (purgatory-based). Метрика ``infra_client_circuit_state`` публикуется
    автоматически. Локальное состояние не хранится — единый источник
    правды на процесс.

    B-04 fix (cycle 38): registered через ``@processor`` декоратор —
    ``core:circuit_breaker``. Spec покрывает threshold/timeout/breaker_name.

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
        """Выполяет processors под Circuit Breaker guard с fallback-цепочкой.

        Создаёт/получает CB из registry (per-route namespace). При открытом
        circuit — переход на fallback processors. При падении основного
        процессора внутри CB guard — также fallback.

        Args:
            exchange: Текущий exchange; route_id используется для breaker-name.
            context: Контекст выполнения маршрута.

        """
        from src.backend.core.resilience.breaker import (
            BreakerSpec,
            CircuitOpen,
            get_breaker_registry,
        )
        from src.backend.dsl.engine.processors.base import run_sub_processors

        breaker_registry = get_breaker_registry()

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


@processor(
    "timeout",
    namespace="core",
    spec_schema={
        "type": "object",
        "description": "Camel Timeout — wrap sub-processors with a time limit.",
        "properties": {
            "seconds": {"type": "number", "minimum": 0, "default": 30.0},
            "name": {"type": "string"},
        },
        "required": [],
    },
    output_schema={
        "type": "object",
        "description": "Exchange; при timeout — failed или fallback exchange.",
    },
    capabilities=("dsl.eip.timeout",),
    tags=("eip", "resilience", "timeout"),
)
class TimeoutProcessor(BaseProcessor):
    """Camel Timeout EIP — wrap sub-processors with a time limit.

    If processing exceeds the timeout, the exchange is failed
    and an optional fallback is executed.

    B-04 fix (cycle 38): registered через ``@processor`` декоратор —
    ``core:timeout``.

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
        """Метод process (см. signature)."""
        from src.backend.dsl.engine.processors.base import run_sub_processors

        try:
            await asyncio.wait_for(
                run_sub_processors(self._processors, exchange, context),
                timeout=self._seconds,
            )
        except TimeoutError:
            exchange.set_property("timeout_exceeded", True)
            exchange.set_property("timeout_limit_seconds", self._seconds)

            if self._fallback:
                await run_sub_processors(self._fallback, exchange, context)
            else:
                exchange.fail(f"Timeout after {self._seconds}s")
