"""Control-flow / resilience миксин для RouteBuilder.

Группа: choice / do_try / retry / parallel / saga / fallback / idempotent /
dead_letter / timeout / loop / throttle / delay / circuit_breaker /
switch / on_error / expire / correlation_id.

Stateless — см. контракт в ``base.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    BaseProcessor,
    ChoiceBranch,
    ChoiceProcessor,
    CircuitBreakerProcessor,
    DeadLetterProcessor,
    DelayProcessor,
    DispatchActionProcessor,
    FallbackChainProcessor,
    HitlApprovalProcessor,
    IdempotentConsumerProcessor,
    LogProcessor,
    ParallelProcessor,
    RetryProcessor,
    SagaProcessor,
    SagaStep,
    ThrottlerProcessor,
    TryCatchProcessor,
)
from src.backend.dsl.engine.processors.streaming import (
    CorrelationIdProcessor,
    MessageExpirationProcessor,
)

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder


class ControlFlowMixin:
    """Поведенческий миксин control-flow / resilience для ``RouteBuilder``.

    Stateless: миксин использует ``self._add`` / ``self._add_lazy`` /
    ``self._processors`` через MRO; собственных полей не содержит.
    Контракт см. в ``base.py``.
    """

    __slots__ = ()

    # ── Ветвление / условия ──

    def choice(
        self,
        when: list[ChoiceBranch]
        | list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
        otherwise: list[BaseProcessor] | None = None,
    ) -> RouteBuilder:
        """When/Otherwise: ветвление по JMESPath-веткам или предикатам.

        Принимает либо новый формат — список :class:`ChoiceBranch` с
        ``expr=<jmespath>`` (поддерживает write-back YAML), либо legacy —
        список ``(predicate, processors)`` с Python-callable (без write-back).
        """
        return self._add(ChoiceProcessor(when=when, otherwise=otherwise))  # type: ignore[attr-defined]

    def switch(
        self,
        field: str,
        cases: dict[str, list[BaseProcessor]],
        *,
        default: list[BaseProcessor] | None = None,
    ) -> RouteBuilder:
        """n8n Switch — case/match роутинг по значению поля."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.patterns",
            "SwitchProcessor",
            field=field,
            cases=cases,
            default=default,
        )

    # ── Обработка ошибок ──

    def do_try(
        self,
        try_processors: list[BaseProcessor],
        catch_processors: list[BaseProcessor] | None = None,
        finally_processors: list[BaseProcessor] | None = None,
    ) -> RouteBuilder:
        """Try/Catch/Finally: exception handling в pipeline."""
        return self._add(  # type: ignore[attr-defined]
            TryCatchProcessor(
                try_processors=try_processors,
                catch_processors=catch_processors,
                finally_processors=finally_processors,
            )
        )

    def retry(
        self,
        processors: list[BaseProcessor],
        *,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        backoff: str = "exponential",
    ) -> RouteBuilder:
        """Retry с backoff: повторяет процессоры при ошибке. backoff: fixed|exponential."""
        return self._add(  # type: ignore[attr-defined]
            RetryProcessor(
                processors=processors,
                max_attempts=max_attempts,
                delay_seconds=delay_seconds,
                backoff=backoff,
            )
        )

    def fallback(self, processors: list[BaseProcessor]) -> RouteBuilder:
        """Fallback-цепочка: последовательно пробует процессоры, останавливается на первом успехе."""
        return self._add(FallbackChainProcessor(processors=processors))  # type: ignore[attr-defined]

    def dead_letter(
        self, processors: list[BaseProcessor], *, dlq_stream: str = "dsl-dlq"
    ) -> RouteBuilder:
        """Dead Letter Channel: при ошибке — отправка в Redis stream."""
        return self._add(  # type: ignore[attr-defined]
            DeadLetterProcessor(processors=processors, dlq_stream=dlq_stream)
        )

    def on_error(
        self,
        *,
        action: str | None = None,
        processors: list[BaseProcessor] | None = None,
        dlq_stream: str = "dsl-dlq",
    ) -> RouteBuilder:
        """Глобальный error handler для pipeline — оборачивает ВСЕ накопленные процессоры.

        При ошибке делегирует в action или выполняет processors, всё попадает в DLQ.

        Usage::

            RouteBuilder.from_("x", source="...")
                .http_call(...)
                .transform(...)
                .on_error(action="dlq.handle")
                .build()
        """
        handler_procs: list[BaseProcessor] = []
        if action:
            handler_procs.append(DispatchActionProcessor(action=action))
        if processors:
            handler_procs.extend(processors)
        if not handler_procs:
            handler_procs.append(LogProcessor(level="error"))

        current = list(self._processors)  # type: ignore[attr-defined]
        self._processors.clear()  # type: ignore[attr-defined]
        wrapped = DeadLetterProcessor(
            processors=current + handler_procs, dlq_stream=dlq_stream
        )
        self._processors.append(wrapped)  # type: ignore[attr-defined]
        return self  # type: ignore[return-value]

    # ── Concurrent / parallel / saga ──

    def parallel(
        self, branches: dict[str, list[BaseProcessor]], *, strategy: str = "all"
    ) -> RouteBuilder:
        """Параллельное выполнение именованных веток. strategy: all|first."""
        return self._add(  # type: ignore[attr-defined]
            ParallelProcessor(branches=branches, strategy=strategy)
        )

    def saga(self, steps: list[SagaStep]) -> RouteBuilder:
        """Saga-паттерн: последовательные шаги с компенсацией при ошибке."""
        return self._add(SagaProcessor(steps=steps))  # type: ignore[attr-defined]

    def idempotent(
        self,
        key_expression: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 86400,
    ) -> RouteBuilder:
        """Идемпотентный consumer: дедупликация через Redis SET NX EX."""
        return self._add(  # type: ignore[attr-defined]
            IdempotentConsumerProcessor(
                key_expression=key_expression, ttl_seconds=ttl_seconds
            )
        )

    # ── Time control / circuit_breaker / loop ──

    def throttle(self, rate: float, *, burst: int = 1) -> RouteBuilder:
        """Throttler: rate-limit N сообщений/сек (token bucket)."""
        return self._add(ThrottlerProcessor(rate=rate, burst=burst))  # type: ignore[attr-defined]

    def delay(
        self,
        delay_ms: int | None = None,
        *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
    ) -> RouteBuilder:
        """Delay: задержка на N миллисекунд или до timestamp."""
        return self._add(  # type: ignore[attr-defined]
            DelayProcessor(delay_ms=delay_ms, scheduled_time_fn=scheduled_time_fn)
        )

    def circuit_breaker(
        self,
        processors: list[BaseProcessor],
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        fallback_processors: list[BaseProcessor] | None = None,
        breaker_name: str | None = None,
    ) -> RouteBuilder:
        """Circuit Breaker: fail-fast при повторных ошибках (CLOSED/OPEN/HALF_OPEN).

        Wave 26.7: state-machine делегируется в shared ``breaker_registry``;
        ``breaker_name`` опционально переопределяет имя (по умолчанию —
        ``dsl.pipeline.<route_id>``), чтобы шарить один breaker между
        несколькими процессорами одного маршрута.
        """
        return self._add(  # type: ignore[attr-defined]
            CircuitBreakerProcessor(
                processors=processors,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                fallback_processors=fallback_processors,
                breaker_name=breaker_name,
            )
        )

    def loop(
        self,
        processors: list[BaseProcessor],
        *,
        count: int | None = None,
        until: Callable[[Exchange[Any]], bool] | None = None,
        max_iterations: int = 1000,
    ) -> RouteBuilder:
        """Loop — execute sub-processors N times or until condition."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip",
            "LoopProcessor",
            processors=processors,
            count=count,
            until=until,
            max_iterations=max_iterations,
        )

    def for_each(
        self,
        items_path: str,
        processors: list[BaseProcessor],
        *,
        copy_exchange: bool = True,
        max_iterations: int = 10000,
    ) -> RouteBuilder:
        """For-Each — iterate over a collection, executing sub-processors for each item.

        Args:
            items_path: JMESPath expression to extract iterable from exchange body.
            processors: Sub-processors to run for each item.
            copy_exchange: If True, each iteration gets a copy of the exchange.
            max_iterations: Maximum number of items to process.
        """
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip",
            "ForEachProcessor",
            items_path=items_path,
            processors=processors,
            copy_exchange=copy_exchange,
            max_iterations=max_iterations,
        )

    def timeout(
        self,
        processors: list[BaseProcessor],
        *,
        seconds: float = 30.0,
        fallback_processors: list[BaseProcessor] | None = None,
    ) -> RouteBuilder:
        """Timeout — wrap sub-processors with a time limit."""
        return self._add_lazy(  # type: ignore[attr-defined]
            "src.backend.dsl.engine.processors.eip",
            "TimeoutProcessor",
            processors=processors,
            seconds=seconds,
            fallback_processors=fallback_processors,
        )

    # ── Expiration / correlation-id ──

    def expire(
        self,
        ttl_seconds: float,
        *,
        header_name: str = "x-created-at",
        drop_action: str = "fail",
    ) -> RouteBuilder:
        """Message Expiration: отбрасывает сообщения старше ``ttl_seconds``."""
        return self._add(  # type: ignore[attr-defined]
            MessageExpirationProcessor(
                ttl_seconds=ttl_seconds,
                header_name=header_name,
                drop_action=drop_action,
            )
        )

    def correlation_id(self, *, header: str = "x-correlation-id") -> RouteBuilder:
        """Correlation Identifier: проставляет/пропагирует correlation-id."""
        return self._add(CorrelationIdProcessor(header=header))  # type: ignore[attr-defined]

    # ── Human-in-the-loop ──

    def hitl_approval(
        self,
        hitl_service: Any,
        *,
        title: str,
        description: str = "",
        approvers: list[str] | None = None,
        timeout_seconds: float = 86_400.0,
        payload_path: str | None = None,
        request_info_processors: list[BaseProcessor] | None = None,
    ) -> RouteBuilder:
        """HITL-approval: приостанавливает pipeline, ожидает approve/reject от оператора.

        Использует :class:`HitlService` для регистрации pending signal и ожидания
        решения. При ``approve`` — pipeline продолжается; при ``reject`` — Exchange
        переводится в failed-состояние; при ``request_info`` — выполняются
        ``request_info_processors`` и signal перерегистрируется.

        Args:
            hitl_service: Экземпляр :class:`HitlService`.
            title: Заголовок запроса (отображается оператору).
            description: Описание запроса.
            approvers: Список user-id для уведомления (пустой = всем).
            timeout_seconds: Максимальное время ожидания (default 24h).
            payload_path: JMESPath к данным в body для формирования payload.
            request_info_processors: Процессоры для сбора доп. информации.

        Example::

            route = (
                RouteBuilder.from_("loan.approve", source="http:/webhook")
                .validate(LoanRequest)
                .http_call("https://bank-api/decision")
                .hitl_approval(
                    hitl_service=hitl_service,
                    title="Кредитное решение требует подтверждения",
                    approvers=["manager@bank.com"],
                )
                .dispatch_action("loan.execute")
                .build()
            )
        """
        return self._add(  # type: ignore[attr-defined]
            HitlApprovalProcessor(
                hitl_service=hitl_service,
                title=title,
                description=description,
                approvers=approvers,
                timeout_seconds=timeout_seconds,
                payload_path=payload_path,
                request_info_processors=request_info_processors,
            )
        )
