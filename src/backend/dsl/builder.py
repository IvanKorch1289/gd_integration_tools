from dataclasses import dataclass, field
from typing import Any, Callable

from src.backend.core.di.dependencies import get_watermark_store_optional
from src.backend.core.interfaces.watermark_store import WatermarkStore
from src.backend.dsl.adapters.types import ProtocolType, TransportConfig
from src.backend.dsl.builders.ai_rpa import AIRPAMixin
from src.backend.dsl.builders.converters import ConvertersMixin
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors import (
    AggregatorProcessor,
    BaseProcessor,
    CallableProcessor,
    CDCProcessor,
    ChoiceBranch,
    ChoiceProcessor,
    CircuitBreakerProcessor,
    ClaimCheckProcessor,
    DeadLetterProcessor,
    DelayProcessor,
    DispatchActionProcessor,
    DynamicRouterProcessor,
    EnrichProcessor,
    FallbackChainProcessor,
    FilterProcessor,
    IdempotentConsumerProcessor,
    LoadBalancerProcessor,
    LogProcessor,
    MulticastProcessor,
    NormalizerProcessor,
    ParallelProcessor,
    PipelineRefProcessor,
    ProcessorCallable,
    RecipientListProcessor,
    ResequencerProcessor,
    RetryProcessor,
    SagaProcessor,
    SagaStep,
    ScatterGatherProcessor,
    SetHeaderProcessor,
    SetPropertyProcessor,
    SplitterProcessor,
    ThrottlerProcessor,
    TransformProcessor,
    TryCatchProcessor,
    ValidateProcessor,
    WireTapProcessor,
)
from src.backend.dsl.engine.processors.invoke import InvokeProcessor
from src.backend.dsl.engine.processors.streaming import (
    ChannelPurgerProcessor,
    CorrelationIdProcessor,
    DurableSubscriberProcessor,
    ExactlyOnceProcessor,
    GroupByKeyProcessor,
    MessageExpirationProcessor,
    ReplyToProcessor,
    SamplingProcessor,
    SchemaRegistryValidator,
    SessionWindowProcessor,
    SlidingWindowProcessor,
    TumblingWindowProcessor,
)

__all__ = ("RouteBuilder",)


@dataclass(slots=True)
class RouteBuilder(AIRPAMixin, ConvertersMixin):
    """Fluent-builder для DSL-маршрутов.

    Пример::

        route = (
            RouteBuilder.from_("tech.send_email", source="internal:tech")
            .dispatch_action("tech.send_email")
            .log()
            .build()
        )
    """

    route_id: str
    source: str | None = None
    description: str | None = None
    _processors: list[BaseProcessor] = field(default_factory=list)
    _protocol: ProtocolType | None = None
    _transport_config: TransportConfig | None = None
    _feature_flag: str | None = None

    # ── Core helpers ──

    @classmethod
    def from_(
        cls, route_id: str, source: str, *, description: str | None = None
    ) -> "RouteBuilder":
        """Точка входа: создаёт новый RouteBuilder.

        Args:
            route_id: Уникальный ID маршрута (e.g., "orders.create").
            source: Источник данных (e.g., "internal:orders", "timer:60s", "webhook:/path").
            description: Человекочитаемое описание маршрута.

        Returns:
            RouteBuilder для fluent-chain вызовов.

        Example::

            route = (
                RouteBuilder.from_("etl.import", source="timer:300s")
                .http_call("https://api.example.com/data")
                .normalize()
                .dispatch_action("analytics.insert_batch")
                .build()
            )
        """
        return cls(route_id=route_id, source=source, description=description)

    @classmethod
    def from_registered_source(
        cls, route_id: str, source_id: str, *, description: str | None = None
    ) -> "RouteBuilder":
        """Точка входа W23: маршрут запитывается от зарегистрированного Source.

        Связь Source → DSL делается на уровне ``services.sources.lifecycle``
        через :class:`SourceToInvokerAdapter`; этот метод нужен только
        для **декларации** в DSL ("этот route ждёт события от source X")
        и метаданных ``Pipeline``.

        Args:
            route_id: Уникальный ID маршрута.
            source_id: ID source-инстанса в :class:`SourceRegistry`.
            description: Человекочитаемое описание.

        Example::

            route = (
                RouteBuilder.from_registered_source("orders.audit", "orders_cdc")
                .normalize()
                .dispatch_action("analytics.insert_batch")
                .build()
            )
        """
        return cls(
            route_id=route_id, source=f"source:{source_id}", description=description
        )

    def _add(self, processor: BaseProcessor) -> "RouteBuilder":
        self._processors.append(processor)
        return self

    def _add_lazy(
        self, import_path: str, class_name: str, **kwargs: Any
    ) -> "RouteBuilder":
        """Lazy import + создание процессора. Для AI/Web/Export/Integration."""
        import importlib

        mod = importlib.import_module(import_path)
        cls = getattr(mod, class_name)
        return self._add(cls(**kwargs))

    # ── Pipeline composition ──

    def process(self, processor: BaseProcessor) -> "RouteBuilder":
        """Добавляет произвольный процессор в pipeline."""
        return self._add(processor)

    def to(self, processor: BaseProcessor) -> "RouteBuilder":
        """Алиас для process() — Camel-style naming."""
        return self._add(processor)

    def process_fn(
        self, func: ProcessorCallable, *, name: str | None = None
    ) -> "RouteBuilder":
        """Добавляет обычную функцию или coroutine как процессор.

        Функция принимает (exchange, context) и модифицирует exchange in-place.
        """
        return self._add(CallableProcessor(func=func, name=name))

    def include(self, other: Pipeline) -> "RouteBuilder":
        """Включает все процессоры из другого Pipeline (композиция)."""
        self._processors.extend(other.processors)
        return self

    # ── Chainable per-step modifiers (Sprint 2 §12.5) ──

    def _last_processor_or_raise(self) -> BaseProcessor:
        """Возвращает последний добавленный processor для chainable-модификации.

        Raises:
            ValueError: если pipeline пуст — модификатор вызван до первого step.
        """
        if not self._processors:
            raise ValueError(
                "with_*-модификатор вызван до первого step — нет предыдущего "
                "processor для модификации"
            )
        return self._processors[-1]

    @staticmethod
    def _set_first_attr(
        obj: Any, candidates: tuple[str, ...], value: Any
    ) -> str | None:
        """Устанавливает значение в первый из существующих candidate-атрибутов."""
        for attr in candidates:
            if hasattr(obj, attr):
                setattr(obj, attr, value)
                return attr
        return None

    def with_timeout(self, seconds: float) -> "RouteBuilder":
        """Переопределяет timeout последнего step.

        Применимо к процессорам, имеющим атрибут ``_timeout`` или ``timeout``
        (HttpCallProcessor, DatabaseQueryProcessor и т.п.).

        Args:
            seconds: Таймаут в секундах (float).

        Raises:
            ValueError: если предыдущий processor не поддерживает timeout.

        Example::

            builder.http_call("https://api.example.com").with_timeout(10.0)
        """
        last = self._last_processor_or_raise()
        if self._set_first_attr(last, ("_timeout", "timeout"), float(seconds)) is None:
            raise ValueError(
                f"with_timeout: processor {type(last).__name__} "
                f"не поддерживает атрибут timeout"
            )
        return self

    def with_retries(
        self, max_attempts: int, *, backoff: str | float | None = None
    ) -> "RouteBuilder":
        """Переопределяет количество попыток retry для предыдущего step.

        Применимо к процессорам, имеющим атрибут ``_max_attempts``,
        ``_max_retries``, ``max_attempts`` или ``max_retries``.

        Args:
            max_attempts: Максимальное количество попыток (включая первую).
            backoff: Опциональный backoff. Тип зависит от processor: для
                ``RetryProcessor`` — строка ``fixed``/``exponential``; для
                кастомных процессоров может быть число.

        Raises:
            ValueError: если предыдущий processor не поддерживает retries.
        """
        last = self._last_processor_or_raise()
        applied = self._set_first_attr(
            last,
            ("_max_attempts", "_max_retries", "max_attempts", "max_retries"),
            int(max_attempts),
        )
        if applied is None:
            raise ValueError(
                f"with_retries: processor {type(last).__name__} "
                f"не поддерживает атрибут retries"
            )
        if backoff is not None:
            self._set_first_attr(
                last, ("_backoff", "_retry_backoff", "backoff"), backoff
            )
        return self

    def with_headers(
        self,
        headers: dict[str, str],
        *,
        mode: str = "merge",
    ) -> "RouteBuilder":
        """Переопределяет HTTP-заголовки предыдущего step.

        Args:
            headers: Словарь заголовков для применения.
            mode: ``merge`` (объединение, override duplicate) или ``replace``
                (полная замена).

        Raises:
            ValueError: если mode не ``merge``/``replace`` или processor не
                поддерживает атрибут headers.
        """
        if mode not in ("merge", "replace"):
            raise ValueError(
                f"with_headers: mode должен быть 'merge' или 'replace', "
                f"получено {mode!r}"
            )
        last = self._last_processor_or_raise()
        for attr in ("_headers", "headers"):
            if hasattr(last, attr):
                current = getattr(last, attr) or {}
                if mode == "replace":
                    setattr(last, attr, dict(headers))
                else:
                    merged = dict(current)
                    merged.update(headers)
                    setattr(last, attr, merged)
                return self
        raise ValueError(
            f"with_headers: processor {type(last).__name__} "
            f"не поддерживает атрибут headers"
        )

    def with_auth(
        self,
        *,
        token: str | None = None,
        api_key: str | None = None,
        mtls_cert: str | None = None,
    ) -> "RouteBuilder":
        """Переопределяет auth для предыдущего step.

        Поддерживается ровно один способ за вызов:
            - ``token``: Bearer-токен через ``_auth_token``.
            - ``api_key``: транслируется в header ``X-API-Key`` (через ``with_headers``).
            - ``mtls_cert``: путь к сертификату через ``_mtls_cert``.

        Raises:
            ValueError: если указано не ровно одно из значений или processor
                не поддерживает соответствующий атрибут.
        """
        provided = [
            v for v in (token, api_key, mtls_cert) if v is not None
        ]
        if len(provided) != 1:
            raise ValueError(
                "with_auth: должен быть указан ровно один из "
                "token/api_key/mtls_cert"
            )
        if api_key is not None:
            return self.with_headers({"X-API-Key": api_key}, mode="merge")
        last = self._last_processor_or_raise()
        if token is not None:
            if self._set_first_attr(last, ("_auth_token", "auth_token"), token) is None:
                raise ValueError(
                    f"with_auth(token=...): processor {type(last).__name__} "
                    f"не поддерживает атрибут auth_token"
                )
            return self
        if mtls_cert is not None:
            if self._set_first_attr(last, ("_mtls_cert", "mtls_cert"), mtls_cert) is None:
                raise ValueError(
                    f"with_auth(mtls_cert=...): processor {type(last).__name__} "
                    f"не поддерживает атрибут mtls_cert"
                )
            return self
        return self

    # ── Core processors ──

    def set_header(self, key: str, value: Any) -> "RouteBuilder":
        """Устанавливает заголовок в in_message."""
        return self._add(SetHeaderProcessor(key=key, value=value))

    def set_property(self, key: str, value: Any) -> "RouteBuilder":
        """Устанавливает runtime-свойство Exchange."""
        return self._add(SetPropertyProcessor(key=key, value=value))

    def dispatch_action(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Вызывает зарегистрированный action (Camel Service Activator).

        Основной способ связи DSL с бизнес-логикой. Action ищется
        в ActionHandlerRegistry по имени (e.g., "orders.add").
        """
        return self._add(
            DispatchActionProcessor(
                action=action,
                payload_factory=payload_factory,
                result_property=result_property,
            )
        )

    def invoke(
        self,
        action: str,
        *,
        mode: str = "sync",
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        reply_channel: str | None = None,
        result_property: str = "invoke_result",
        invocation_id_property: str = "invocation_id",
        timeout: float | None = None,
        correlation_id: str | None = None,
    ) -> "RouteBuilder":
        """Вызывает action через :class:`Invoker` (W22) с заданным режимом.

        В отличие от :meth:`dispatch_action`, поддерживает шесть режимов
        (``sync``/``async-api``/``async-queue``/``deferred``/``background``/
        ``streaming``) и возвращает единый ``invocation_id`` для трассировки
        и polling-результата через ReplyChannel registry.

        ``timeout`` ограничивает SYNC-исполнение через ``asyncio.wait_for``;
        ``correlation_id`` — клиентский id для трассировки middleware/reply.
        """
        return self._add(
            InvokeProcessor(
                action=action,
                mode=mode,
                payload_factory=payload_factory,
                reply_channel=reply_channel,
                result_property=result_property,
                invocation_id_property=invocation_id_property,
                timeout=timeout,
                correlation_id=correlation_id,
            )
        )

    def transform(self, expression: str) -> "RouteBuilder":
        """Трансформирует body через JMESPath-выражение."""
        return self._add(TransformProcessor(expression=expression))

    def filter(self, predicate: Callable[[Exchange[Any]], bool]) -> "RouteBuilder":
        """Фильтрует Exchange — останавливает, если predicate=False."""
        return self._add(FilterProcessor(predicate=predicate))

    def enrich(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "enrichment",
    ) -> "RouteBuilder":
        return self._add(
            EnrichProcessor(
                action=action,
                payload_factory=payload_factory,
                result_property=result_property,
            )
        )

    def log(self, level: str = "info") -> "RouteBuilder":
        """Логирование текущего состояния Exchange (для отладки)."""
        return self._add(LogProcessor(level=level))

    def validate(self, model: type) -> "RouteBuilder":
        """Pydantic-валидация body; при ошибке Exchange останавливается."""
        return self._add(ValidateProcessor(model=model))

    def auth(
        self,
        methods: list[str] | str = "api_key",
        *,
        result_property: str = "auth",
        required: bool = True,
    ) -> "RouteBuilder":
        """Проверяет авторизацию запроса (Wave 8.1).

        Args:
            methods: Один или список разрешённых AuthMethod
                (``api_key`` / ``jwt`` / ``express_jwt`` / ``mtls`` / ``basic``).
            result_property: Имя property для AuthContext.
            required: Если True — при провале маршрут останавливается.
        """
        from src.backend.dsl.engine.processors.security import AuthValidateProcessor

        return self._add(
            AuthValidateProcessor(
                methods=methods, result_property=result_property, required=required
            )
        )

    # ── Integration processors ──

    # mcp_tool / agent_graph — перенесены в dsl.builders.ai_rpa.AIRPAMixin
    # (Stage 2.2). Доступны через MRO у RouteBuilder.

    def cdc(
        self,
        profile: str,
        tables: list[str],
        target_action: str,
        *,
        strategy: str = "polling",
        interval: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        channel: str | None = None,
    ) -> "RouteBuilder":
        """Change Data Capture — подписка на изменения в БД.

        strategy: polling (любая БД), listen_notify (PostgreSQL), logminer (Oracle).
        """
        return self._add(
            CDCProcessor(
                profile=profile,
                tables=tables,
                target_action=target_action,
                strategy=strategy,
                interval=interval,
                timestamp_column=timestamp_column,
                batch_size=batch_size,
                channel=channel,
            )
        )

    # ── Control flow ──

    def choice(
        self,
        when: list[ChoiceBranch]
        | list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
        otherwise: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Camel When/Otherwise: ветвление по JMESPath-веткам или предикатам.

        Принимает либо новый формат — список :class:`ChoiceBranch` с
        ``expr=<jmespath>`` (поддерживает write-back YAML), либо legacy —
        список ``(predicate, processors)`` с Python-callable (без write-back).
        """
        return self._add(ChoiceProcessor(when=when, otherwise=otherwise))

    def do_try(
        self,
        try_processors: list[BaseProcessor],
        catch_processors: list[BaseProcessor] | None = None,
        finally_processors: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Camel Try/Catch/Finally: exception handling в pipeline."""
        return self._add(
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
    ) -> "RouteBuilder":
        """Retry с backoff: повторяет процессоры при ошибке. backoff: fixed|exponential."""
        return self._add(
            RetryProcessor(
                processors=processors,
                max_attempts=max_attempts,
                delay_seconds=delay_seconds,
                backoff=backoff,
            )
        )

    def to_route(
        self, route_id: str, *, result_property: str = "sub_result"
    ) -> "RouteBuilder":
        """Вызов другого зарегистрированного DSL-маршрута."""
        return self._add(
            PipelineRefProcessor(route_id=route_id, result_property=result_property)
        )

    def parallel(
        self, branches: dict[str, list[BaseProcessor]], *, strategy: str = "all"
    ) -> "RouteBuilder":
        """Параллельное выполнение именованных веток. strategy: all|first."""
        return self._add(ParallelProcessor(branches=branches, strategy=strategy))

    def saga(self, steps: list[SagaStep]) -> "RouteBuilder":
        """Saga-паттерн: последовательные шаги с компенсацией при ошибке."""
        return self._add(SagaProcessor(steps=steps))

    def dead_letter(
        self, processors: list[BaseProcessor], *, dlq_stream: str = "dsl-dlq"
    ) -> "RouteBuilder":
        """Dead Letter Channel: при ошибке — отправка в Redis stream."""
        return self._add(
            DeadLetterProcessor(processors=processors, dlq_stream=dlq_stream)
        )

    def idempotent(
        self,
        key_expression: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 86400,
    ) -> "RouteBuilder":
        """Идемпотентный consumer: дедупликация через Redis SET NX EX."""
        return self._add(
            IdempotentConsumerProcessor(
                key_expression=key_expression, ttl_seconds=ttl_seconds
            )
        )

    def fallback(self, processors: list[BaseProcessor]) -> "RouteBuilder":
        """Fallback-цепочка: последовательно пробует процессоры, останавливается на первом успехе."""
        return self._add(FallbackChainProcessor(processors=processors))

    def wire_tap(self, tap_processors: list[BaseProcessor]) -> "RouteBuilder":
        """Wire Tap: копия Exchange в побочный канал без влияния на основной поток."""
        return self._add(WireTapProcessor(tap_processors=tap_processors))

    # ── EIP processors ──

    def translate(self, from_format: str, to_format: str) -> "RouteBuilder":
        """DEPRECATED: используйте .convert(). translate() — alias для обратной совместимости."""
        return self.convert(from_format=from_format, to_format=to_format)

    def dynamic_route(
        self, route_expression: Callable[[Exchange[Any]], str]
    ) -> "RouteBuilder":
        """Camel Dynamic Router: runtime-вычисление route_id."""
        return self._add(DynamicRouterProcessor(route_expression=route_expression))

    def scatter_gather(
        self,
        route_ids: list[str],
        *,
        aggregation: str = "merge",
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Camel Scatter-Gather: fan-out на N маршрутов + сборка результатов."""
        return self._add(
            ScatterGatherProcessor(
                route_ids=route_ids,
                aggregation=aggregation,
                timeout_seconds=timeout_seconds,
            )
        )

    def throttle(self, rate: float, *, burst: int = 1) -> "RouteBuilder":
        """Camel Throttler: rate-limit N сообщений/сек (token bucket)."""
        return self._add(ThrottlerProcessor(rate=rate, burst=burst))

    def delay(
        self,
        delay_ms: int | None = None,
        *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
    ) -> "RouteBuilder":
        """Camel Delay: задержка на N миллисекунд или до timestamp."""
        return self._add(
            DelayProcessor(delay_ms=delay_ms, scheduled_time_fn=scheduled_time_fn)
        )

    def split(self, expression: str, processors: list[BaseProcessor]) -> "RouteBuilder":
        """Camel Splitter: разбиение массива на отдельные Exchange по JMESPath."""
        return self._add(
            SplitterProcessor(expression=expression, processors=processors)
        )

    def aggregate(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Camel Aggregator: собирает N Exchange по correlation_key в batch."""
        return self._add(
            AggregatorProcessor(
                correlation_key=correlation_key,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
            )
        )

    def recipient_list(
        self,
        recipients_expression: Callable[[Exchange[Any]], list[str]],
        *,
        parallel: bool = True,
    ) -> "RouteBuilder":
        """Camel Recipient List: динамический fan-out на список маршрутов."""
        return self._add(
            RecipientListProcessor(
                recipients_expression=recipients_expression, parallel=parallel
            )
        )

    # ── Camel EIP v2 ──

    def load_balance(
        self,
        targets: list[str],
        *,
        strategy: str = "round_robin",
        weights: list[float] | None = None,
        sticky_header: str | None = None,
    ) -> "RouteBuilder":
        """Camel Load Balancer: round_robin/random/weighted/sticky распределение."""
        return self._add(
            LoadBalancerProcessor(
                targets=targets,
                strategy=strategy,
                weights=weights,
                sticky_header=sticky_header,
            )
        )

    def circuit_breaker(
        self,
        processors: list[BaseProcessor],
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        fallback_processors: list[BaseProcessor] | None = None,
        breaker_name: str | None = None,
    ) -> "RouteBuilder":
        """Camel Circuit Breaker: fail-fast при повторных ошибках (CLOSED/OPEN/HALF_OPEN).

        Wave 26.7: state-machine делегируется в shared ``breaker_registry``;
        ``breaker_name`` опционально переопределяет имя (по умолчанию —
        ``dsl.pipeline.<route_id>``), чтобы шарить один breaker между
        несколькими процессорами одного маршрута.
        """
        return self._add(
            CircuitBreakerProcessor(
                processors=processors,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                fallback_processors=fallback_processors,
                breaker_name=breaker_name,
            )
        )

    def claim_check_in(
        self, *, store: str = "redis", ttl_seconds: int = 3600
    ) -> "RouteBuilder":
        """Camel Claim Check (store): сохраняет body в Redis, body → {_claim_token: ...}."""
        return self._add(
            ClaimCheckProcessor(mode="store", store=store, ttl_seconds=ttl_seconds)
        )

    def claim_check_out(self) -> "RouteBuilder":
        """Camel Claim Check (retrieve): восстанавливает body по _claim_token."""
        return self._add(ClaimCheckProcessor(mode="retrieve"))

    def normalize(self, target_schema: type | None = None) -> "RouteBuilder":
        """Camel Normalizer: автоопределение формата (XML/CSV/YAML/JSON) → canonical dict."""
        return self._add(NormalizerProcessor(target_schema=target_schema))

    def resequence(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        sequence_field: str = "seq",
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Camel Resequencer: восстановление порядка сообщений по sequence_field."""
        return self._add(
            ResequencerProcessor(
                correlation_key=correlation_key,
                sequence_field=sequence_field,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
            )
        )

    def multicast(
        self,
        branches: list[list[BaseProcessor]],
        *,
        strategy: str = "all",
        stop_on_error: bool = False,
    ) -> "RouteBuilder":
        """Camel Multicast: fan-out на flat list процессор-групп + aggregation."""
        return self._add(
            MulticastProcessor(
                branches=branches, strategy=strategy, stop_on_error=stop_on_error
            )
        )

    def loop(
        self,
        processors: list[BaseProcessor],
        *,
        count: int | None = None,
        until: Callable[[Exchange[Any]], bool] | None = None,
        max_iterations: int = 1000,
    ) -> "RouteBuilder":
        """Camel Loop — execute sub-processors N times or until condition."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.eip",
            "LoopProcessor",
            processors=processors,
            count=count,
            until=until,
            max_iterations=max_iterations,
        )

    def on_completion(
        self,
        processors: list[BaseProcessor],
        *,
        on_success_only: bool = False,
        on_failure_only: bool = False,
    ) -> "RouteBuilder":
        """Camel OnCompletion — run callback after pipeline finishes (like finally)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.eip",
            "OnCompletionProcessor",
            processors=processors,
            on_success_only=on_success_only,
            on_failure_only=on_failure_only,
        )

    def sort(
        self,
        *,
        key_fn: Callable[[Any], Any] | None = None,
        key_field: str | None = None,
        reverse: bool = False,
    ) -> "RouteBuilder":
        """Camel Sort — sort list body by key function or field name."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.eip",
            "SortProcessor",
            key_fn=key_fn,
            key_field=key_field,
            reverse=reverse,
        )

    def timeout(
        self,
        processors: list[BaseProcessor],
        *,
        seconds: float = 30.0,
        fallback_processors: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Camel Timeout — wrap sub-processors with a time limit."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.eip",
            "TimeoutProcessor",
            processors=processors,
            seconds=seconds,
            fallback_processors=fallback_processors,
        )

    # ── Config ──

    def protocol(self, proto: ProtocolType) -> "RouteBuilder":
        """Привязывает маршрут к конкретному протоколу (REST/SOAP/gRPC/...)."""
        self._protocol = proto
        return self

    def transport(self, config: TransportConfig) -> "RouteBuilder":
        """Настройки транспорта (endpoint, timeout, retry_count, options)."""
        self._transport_config = config
        return self

    def feature_flag(self, name: str) -> "RouteBuilder":
        """Привязывает маршрут к feature flag (можно отключить без рестарта)."""
        self._feature_flag = name
        return self

    # ── Proxy pass-through (Wave 3.5 / ADR-014) ──

    def expose_proxy(
        self,
        src: str,
        *,
        methods: list[str] | None = None,
        header_map: dict[str, Any] | None = None,
    ) -> "RouteBuilder":
        """Объявить роут как прокси-вход.

        Args:
            src: ``<protocol>:<address>`` (``http:/api/payments``,
                ``kafka:orders.in`` и т.п.).
            methods: HTTP-методы (для ``http``). ``None`` = все.
            header_map: Опциональный словарь ``{add|drop|override}`` для
                политики inbound-headers.
        """
        from src.backend.dsl.engine.processors.proxy import (
            ExposeProxyProcessor,
            HeaderMapPolicy,
        )

        return self._add(
            ExposeProxyProcessor(
                src=src,
                methods=methods,
                header_policy=HeaderMapPolicy.from_dict(header_map),
            )
        )

    def forward_to(
        self,
        dst: str,
        *,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> "RouteBuilder":
        """Переслать текущее сообщение в backend без трансформаций."""
        from src.backend.dsl.engine.processors.proxy import (
            ForwardToProcessor,
            HeaderMapPolicy,
        )

        return self._add(
            ForwardToProcessor(
                dst=dst,
                pass_headers=pass_headers,
                header_policy=HeaderMapPolicy.from_dict(header_map),
                rewrite_path=rewrite_path,
                timeout=timeout,
            )
        )

    def proxy(
        self,
        src: str,
        dst: str,
        *,
        methods: list[str] | None = None,
        pass_headers: bool = True,
        header_map: dict[str, Any] | None = None,
        rewrite_path: str | None = None,
        timeout: float = 30.0,
    ) -> "RouteBuilder":
        """Сокращение: ``expose_proxy(src) → forward_to(dst)``."""
        return self.expose_proxy(
            src=src, methods=methods, header_map=header_map
        ).forward_to(
            dst=dst,
            pass_headers=pass_headers,
            header_map=header_map,
            rewrite_path=rewrite_path,
            timeout=timeout,
        )

    def redirect(
        self,
        target_url: str | None = None,
        *,
        status_code: int = 302,
        url_source: str | None = None,
        source_key: str | None = None,
        allowed_hosts: list[str] | None = None,
    ) -> "RouteBuilder":
        """Добавляет HTTP-redirect в маршрут.

        Args:
            target_url: Фиксированный URL назначения (``mode=static``).
                Если задан — используется static-режим.
            status_code: HTTP-статус редиректа (301/302/307/308). По умолчанию 302.
            url_source: Источник URL для proxy-режима:
                ``header`` | ``body_field`` | ``exchange_var`` | ``query_param``.
            source_key: Ключ для извлечения URL из источника.
            allowed_hosts: Белый список хостов (для ``url_source=query_param``).
        """
        from src.backend.dsl.engine.processors.proxy import RedirectProcessor

        if target_url is not None:
            return self._add(
                RedirectProcessor(
                    mode="static", status_code=status_code, target_url=target_url
                )
            )
        return self._add(
            RedirectProcessor(
                mode="proxy",
                status_code=status_code,
                url_source=url_source,
                source_key=source_key,
                allowed_hosts=allowed_hosts,
            )
        )

    def windowed_dedup(
        self,
        key_from: str,
        *,
        key_prefix: str = "dedup",
        window_seconds: int = 60,
        mode: str = "first",
    ) -> "RouteBuilder":
        """Дедупликация в скользящем окне с Redis-персистентностью.

        Args:
            key_from: Точечный путь к ключу (напр. ``body.entity_id``).
            key_prefix: Пространство имён Redis-ключей.
            window_seconds: Длительность окна в секундах.
            mode: Режим — ``first`` | ``last`` | ``unique``.
        """
        from src.backend.dsl.engine.processors.eip.windowed_dedup import (
            WindowedDedupProcessor,
        )

        return self._add(
            WindowedDedupProcessor(
                key_from=key_from,
                key_prefix=key_prefix,
                window_seconds=window_seconds,
                mode=mode,
            )
        )

    def windowed_collect(
        self,
        key_from: str,
        dedup_by: str,
        *,
        window_seconds: int = 60,
        dedup_mode: str = "last",
        inject_as: str = "collected_batch",
    ) -> "RouteBuilder":
        """Накопление и батч-дедупликация сообщений в окне.

        Args:
            key_from: Путь к ключу группировки (напр. ``body.table_name``).
            dedup_by: Путь к полю дедупликации внутри батча.
            window_seconds: Длительность окна в секундах.
            dedup_mode: ``first`` | ``last`` — какое значение сохранять.
            inject_as: Имя exchange-свойства для инжекции батча.
        """
        from src.backend.dsl.engine.processors.eip.windowed_dedup import (
            WindowedCollectProcessor,
        )

        return self._add(
            WindowedCollectProcessor(
                key_from=key_from,
                window_seconds=window_seconds,
                dedup_by=dedup_by,
                dedup_mode=dedup_mode,
                inject_as=inject_as,
            )
        )

    def multicast_routes(
        self,
        route_ids: list[str],
        *,
        strategy: str = "all",
        on_error: str = "continue",
        timeout: float = 30.0,
    ) -> "RouteBuilder":
        """Fan-out на зарегистрированные DSL-маршруты по route_id.

        Args:
            route_ids: Список route_id из RouteRegistry.
            strategy: ``all`` — выполнить все; ``first_success`` — остановить после первого.
            on_error: ``fail`` | ``continue`` — поведение при ошибке.
            timeout: Таймаут каждого маршрута в секундах.
        """
        from src.backend.dsl.engine.processors.eip.routing import (
            MulticastRoutesProcessor,
        )

        return self._add(
            MulticastRoutesProcessor(
                route_ids=route_ids,
                strategy=strategy,
                on_error=on_error,
                timeout=timeout,
            )
        )

    # ── Express BotX (Wave 4.2) ──

    def express_send(
        self,
        body: str | None = None,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        body_from: str | None = None,
        bubble: list[list[dict[str, Any]]] | None = None,
        keyboard: list[list[dict[str, Any]]] | None = None,
        status: str = "ok",
        silent_response: bool = False,
        sync: bool = False,
        result_property: str = "express_sync_id",
    ) -> "RouteBuilder":
        """Отправить сообщение в Express чат через BotX API."""
        from src.backend.dsl.engine.processors.express import ExpressSendProcessor

        return self._add(
            ExpressSendProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                body=body,
                body_from=body_from,
                bubble=bubble,
                keyboard=keyboard,
                status=status,
                silent_response=silent_response,
                sync=sync,
                result_property=result_property,
            )
        )

    def express_reply(
        self,
        body_from: str | None = None,
        *,
        bot: str = "main_bot",
        source_sync_id_from: str = "header.X-Express-Sync-Id",
        chat_id_from: str = "body.group_chat_id",
        body: str | None = None,
        result_property: str = "express_reply_sync_id",
    ) -> "RouteBuilder":
        """Ответить на исходное сообщение Express (reply-thread)."""
        from src.backend.dsl.engine.processors.express import ExpressReplyProcessor

        return self._add(
            ExpressReplyProcessor(
                bot=bot,
                source_sync_id_from=source_sync_id_from,
                chat_id_from=chat_id_from,
                body=body,
                body_from=body_from,
                result_property=result_property,
            )
        )

    def express_edit(
        self,
        sync_id_from: str = "properties.express_sync_id",
        *,
        bot: str = "main_bot",
        body: str | None = None,
        body_from: str | None = None,
        bubble: list[list[dict[str, Any]]] | None = None,
        keyboard: list[list[dict[str, Any]]] | None = None,
        status: str | None = None,
    ) -> "RouteBuilder":
        """Редактировать ранее отправленное Express сообщение."""
        from src.backend.dsl.engine.processors.express import ExpressEditProcessor

        return self._add(
            ExpressEditProcessor(
                bot=bot,
                sync_id_from=sync_id_from,
                body=body,
                body_from=body_from,
                bubble=bubble,
                keyboard=keyboard,
                status=status,
            )
        )

    def express_typing(
        self,
        action: str = "start",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
    ) -> "RouteBuilder":
        """Отправить/остановить индикатор набора в Express чате."""
        from src.backend.dsl.engine.processors.express import ExpressTypingProcessor

        return self._add(
            ExpressTypingProcessor(bot=bot, chat_id_from=chat_id_from, action=action)
        )

    def express_send_file(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.group_chat_id",
        s3_key_from: str | None = None,
        file_data_property: str | None = None,
        file_name: str | None = None,
        file_name_from: str | None = None,
        body: str | None = None,
        body_from: str | None = None,
        result_property: str = "express_file_sync_id",
    ) -> "RouteBuilder":
        """Отправить файл (S3/LocalFS или exchange-property) в Express чат."""
        from src.backend.dsl.engine.processors.express import ExpressSendFileProcessor

        return self._add(
            ExpressSendFileProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                s3_key_from=s3_key_from,
                file_data_property=file_data_property,
                file_name=file_name,
                file_name_from=file_name_from,
                body=body,
                body_from=body_from,
                result_property=result_property,
            )
        )

    def express_mention(
        self,
        *,
        mention_type: str = "user",
        target_from: str | None = None,
        mention_id: str | None = None,
        name_from: str | None = None,
        property_name: str = "express_mentions",
    ) -> "RouteBuilder":
        """Добавить упоминание (user/chat/channel/contact/all) в exchange-property."""
        from src.backend.dsl.engine.processors.express import ExpressMentionProcessor

        return self._add(
            ExpressMentionProcessor(
                mention_type=mention_type,
                target_from=target_from,
                mention_id=mention_id,
                name_from=name_from,
                property_name=property_name,
            )
        )

    def express_status(
        self,
        *,
        bot: str = "main_bot",
        sync_id_from: str = "properties.express_sync_id",
        result_property: str = "express_event_status",
    ) -> "RouteBuilder":
        """Запросить статус доставки сообщения по sync_id."""
        from src.backend.dsl.engine.processors.express import ExpressStatusProcessor

        return self._add(
            ExpressStatusProcessor(
                bot=bot, sync_id_from=sync_id_from, result_property=result_property
            )
        )

    # ── Telegram Bot API (W15.3) ──

    def telegram_send(
        self,
        body: str | None = None,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        body_from: str | None = None,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
        reply_keyboard: list[list[str]] | None = None,
        disable_notification: bool = False,
        disable_web_page_preview: bool = False,
        result_property: str = "telegram_message_id",
    ) -> "RouteBuilder":
        """Отправить сообщение в Telegram чат через Bot API."""
        from src.backend.dsl.engine.processors.telegram import TelegramSendProcessor

        return self._add(
            TelegramSendProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                body=body,
                body_from=body_from,
                parse_mode=parse_mode,
                inline_keyboard=inline_keyboard,
                reply_keyboard=reply_keyboard,
                disable_notification=disable_notification,
                disable_web_page_preview=disable_web_page_preview,
                result_property=result_property,
            )
        )

    def telegram_reply(
        self,
        body_from: str | None = None,
        *,
        bot: str = "main_bot",
        source_message_id_from: str = "body.message.message_id",
        chat_id_from: str = "body.chat_id",
        body: str | None = None,
        parse_mode: str = "HTML",
        result_property: str = "telegram_reply_message_id",
    ) -> "RouteBuilder":
        """Ответить на сообщение Telegram (reply_to_message_id)."""
        from src.backend.dsl.engine.processors.telegram import TelegramReplyProcessor

        return self._add(
            TelegramReplyProcessor(
                bot=bot,
                source_message_id_from=source_message_id_from,
                chat_id_from=chat_id_from,
                body=body,
                body_from=body_from,
                parse_mode=parse_mode,
                result_property=result_property,
            )
        )

    def telegram_edit(
        self,
        message_id_from: str = "properties.telegram_message_id",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
    ) -> "RouteBuilder":
        """Редактировать ранее отправленное Telegram-сообщение."""
        from src.backend.dsl.engine.processors.telegram import TelegramEditProcessor

        return self._add(
            TelegramEditProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                message_id_from=message_id_from,
                body=body,
                body_from=body_from,
                parse_mode=parse_mode,
                inline_keyboard=inline_keyboard,
            )
        )

    def telegram_typing(
        self,
        action: str = "typing",
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
    ) -> "RouteBuilder":
        """Отправить chat-action (typing / upload_photo / …) в Telegram."""
        from src.backend.dsl.engine.processors.telegram import TelegramTypingProcessor

        return self._add(
            TelegramTypingProcessor(bot=bot, chat_id_from=chat_id_from, action=action)
        )

    def telegram_send_file(
        self,
        *,
        bot: str = "main_bot",
        chat_id_from: str = "body.chat_id",
        s3_key_from: str | None = None,
        file_data_property: str | None = None,
        file_name: str | None = None,
        file_name_from: str | None = None,
        body: str | None = None,
        body_from: str | None = None,
        parse_mode: str = "HTML",
        disable_notification: bool = False,
        result_property: str = "telegram_file_message_id",
    ) -> "RouteBuilder":
        """Отправить файл (документ) в Telegram чат."""
        from src.backend.dsl.engine.processors.telegram import TelegramSendFileProcessor

        return self._add(
            TelegramSendFileProcessor(
                bot=bot,
                chat_id_from=chat_id_from,
                s3_key_from=s3_key_from,
                file_data_property=file_data_property,
                file_name=file_name,
                file_name_from=file_name_from,
                body=body,
                body_from=body_from,
                parse_mode=parse_mode,
                disable_notification=disable_notification,
                result_property=result_property,
            )
        )

    def telegram_mention(
        self,
        *,
        user_id_from: str,
        display_name_from: str | None = None,
        parse_mode: str = "MarkdownV2",
        property_name: str = "telegram_mention",
        append: bool = False,
    ) -> "RouteBuilder":
        """Создать фрагмент-упоминание пользователя для вставки в текст."""
        from src.backend.dsl.engine.processors.telegram import TelegramMentionProcessor

        return self._add(
            TelegramMentionProcessor(
                user_id_from=user_id_from,
                display_name_from=display_name_from,
                parse_mode=parse_mode,
                property_name=property_name,
                append=append,
            )
        )

    def telegram_status(
        self, *, bot: str = "main_bot", result_property: str = "telegram_bot_profile"
    ) -> "RouteBuilder":
        """Запросить профиль бота (getMe) — health-check Telegram."""
        from src.backend.dsl.engine.processors.telegram import TelegramStatusProcessor

        return self._add(
            TelegramStatusProcessor(bot=bot, result_property=result_property)
        )

    # ── Entity CRUD (Wave 11) ──

    def entity_create(
        self,
        *,
        entity: str,
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Создать сущность через action ``<entity>.create``."""
        from src.backend.dsl.engine.processors.entity import EntityCreateProcessor

        return self._add(
            EntityCreateProcessor(
                entity=entity,
                payload_from=payload_from,
                result_property=result_property,
            )
        )

    def entity_get(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Прочитать сущность через action ``<entity>.get``."""
        from src.backend.dsl.engine.processors.entity import EntityGetProcessor

        return self._add(
            EntityGetProcessor(
                entity=entity, id_from=id_from, result_property=result_property
            )
        )

    def entity_update(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        payload_from: str = "body",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Обновить сущность через action ``<entity>.update``."""
        from src.backend.dsl.engine.processors.entity import EntityUpdateProcessor

        return self._add(
            EntityUpdateProcessor(
                entity=entity,
                id_from=id_from,
                payload_from=payload_from,
                result_property=result_property,
            )
        )

    def entity_delete(
        self,
        *,
        entity: str,
        id_from: str = "body.id",
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Удалить сущность через action ``<entity>.delete``."""
        from src.backend.dsl.engine.processors.entity import EntityDeleteProcessor

        return self._add(
            EntityDeleteProcessor(
                entity=entity, id_from=id_from, result_property=result_property
            )
        )

    def entity_list(
        self,
        *,
        entity: str,
        filters_from: str | None = "body.filters",
        page: int | None = None,
        size: int | None = None,
        page_from: str | None = None,
        size_from: str | None = None,
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Получить страницу сущностей через action ``<entity>.list``."""
        from src.backend.dsl.engine.processors.entity import EntityListProcessor

        return self._add(
            EntityListProcessor(
                entity=entity,
                filters_from=filters_from,
                page=page,
                size=size,
                page_from=page_from,
                size_from=size_from,
                result_property=result_property,
            )
        )

    # ── Audit + AV (Wave 11) ──

    def audit(
        self,
        *,
        action: str | None = None,
        action_from: str | None = None,
        actor: str = "system",
        actor_from: str | None = None,
        resource_from: str | None = None,
        outcome: str = "success",
        outcome_from: str | None = None,
        metadata_from: str | None = None,
        tenant_id_from: str | None = None,
        correlation_id_from: str | None = None,
        result_property: str = "audit_event_hash",
    ) -> "RouteBuilder":
        """Записать событие в immutable audit log (Wave 5.1)."""
        from src.backend.dsl.engine.processors.audit import AuditProcessor

        return self._add(
            AuditProcessor(
                action=action,
                action_from=action_from,
                actor=actor,
                actor_from=actor_from,
                resource_from=resource_from,
                outcome=outcome,
                outcome_from=outcome_from,
                metadata_from=metadata_from,
                tenant_id_from=tenant_id_from,
                correlation_id_from=correlation_id_from,
                result_property=result_property,
            )
        )

    def scan_file(
        self,
        *,
        s3_key_from: str | None = None,
        data_property: str | None = None,
        on_threat: str = "fail",
        result_property: str = "antivirus_scan_result",
    ) -> "RouteBuilder":
        """Сканировать файл AV-бэкендом (Wave 2.4)."""
        from src.backend.dsl.engine.processors.scan_file import ScanFileProcessor

        return self._add(
            ScanFileProcessor(
                s3_key_from=s3_key_from,
                data_property=data_property,
                on_threat=on_threat,
                result_property=result_property,
            )
        )

    # ── Camel Components (source/sink) ──

    def http_call(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> "RouteBuilder":
        """HTTP client: GET/POST/PUT/DELETE с таймаутом и headers."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "HttpCallProcessor",
            url=url,
            method=method,
            headers=headers,
            auth_token=auth_token,
            timeout=timeout,
            result_property=result_property,
        )

    def db_query(
        self, sql: str, *, result_property: str = "db_result"
    ) -> "RouteBuilder":
        """SQL-запрос через SQLAlchemy (с валидацией: DDL/multi-statement запрещены)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "DatabaseQueryProcessor",
            sql=sql,
            result_property=result_property,
        )

    def read_file(
        self, path: str | None = None, *, binary: bool = False
    ) -> "RouteBuilder":
        """Чтение локального файла в body (text или bytes)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "FileReadProcessor",
            path=path,
            binary=binary,
        )

    def write_file(
        self, path: str | None = None, *, format: str = "auto"
    ) -> "RouteBuilder":
        """Запись body в файл. format: auto|json|csv|text."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "FileWriteProcessor",
            path=path,
            format=format,
        )

    def read_s3(
        self, bucket: str | None = None, key: str | None = None
    ) -> "RouteBuilder":
        """Загрузка объекта из S3."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "S3ReadProcessor",
            bucket=bucket,
            key=key,
        )

    def write_s3(
        self,
        bucket: str | None = None,
        key: str | None = None,
        *,
        content_type: str = "application/octet-stream",
    ) -> "RouteBuilder":
        """Выгрузка body в S3."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "S3WriteProcessor",
            bucket=bucket,
            key=key,
            content_type=content_type,
        )

    def timer(
        self,
        *,
        interval_seconds: float | None = None,
        cron: str | None = None,
        max_fires: int | None = None,
    ) -> "RouteBuilder":
        """Scheduled event source: интервал или cron-выражение."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "TimerProcessor",
            interval_seconds=interval_seconds,
            cron=cron,
            max_fires=max_fires,
        )

    def poll(
        self,
        source_action: str,
        *,
        payload: dict[str, Any] | None = None,
        result_property: str = "polled_data",
    ) -> "RouteBuilder":
        """Periodically вызывает action, результат → body."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.components",
            "PollingConsumerProcessor",
            source_action=source_action,
            payload=payload,
            result_property=result_property,
        )

    # convert / polars_* / dask_compute / duckdb_query / avro_* / protobuf_* /
    # toml_* / markdown_to_html / html_to_markdown / jsonl_* — перенесены в
    # dsl.builders.converters.ConvertersMixin (Stage 2.1).

    # ── Wave 6.2: External DB query (произвольный SQL по profile) ──

    def db_query_external(
        self,
        profile: str,
        sql: str,
        *,
        params_from: str = "body",
        result_property: str = "db_result",
        fetch: str = "all",
        commit: bool = False,
    ) -> "RouteBuilder":
        """Выполняет произвольный SQL во внешней БД по profile-имени.

        Использует ``ExternalDatabaseRegistry`` (через DI) для получения
        async-сессии. Параметры берутся из body / properties / headers.
        """
        return self._add_lazy(
            "src.backend.dsl.engine.processors.db_query_external",
            "ExternalDbQueryProcessor",
            profile=profile,
            sql=sql,
            params_from=params_from,
            result_property=result_property,
            fetch=fetch,
            commit=commit,
        )

    # ── Wave 6.3: Composed Message Processor (последний EIP, 30/30) ──

    def composed_message(
        self,
        splitter: Callable[[Exchange[Any]], Any],
        processors: list[BaseProcessor],
        aggregator: Callable[[list[Exchange[Any]]], Any],
    ) -> "RouteBuilder":
        """Camel «Composed Message Processor»: split → per-part → aggregate."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.composed_message",
            "ComposedMessageProcessor",
            splitter=splitter,
            processors=processors,
            aggregator=aggregator,
        )

    # ── Scraping Pipeline ──

    # scrape / paginate / api_proxy — перенесены в
    # dsl.builders.ai_rpa.AIRPAMixin (Stage 2.2).

    # ── AI Pipeline ──

    # rag_search / compose_prompt / call_llm / parse_llm_output / token_budget /
    # sanitize_pii / restore_pii / get_feedback_examples / publish_event /
    # load_memory / save_memory — перенесены в dsl.builders.ai_rpa.AIRPAMixin
    # (Stage 2.2). Доступны через MRO у RouteBuilder.

    # ── Web Automation (RPA) ──

    # navigate / click / fill_form / extract / screenshot / run_scenario —
    # перенесены в dsl.builders.ai_rpa.AIRPAMixin (Stage 2.2).

    # dq_check / export — перенесены в dsl.builders.converters.ConvertersMixin (Stage 2.1).

    # ── Notify ──

    def notify(
        self,
        channel: str = "email",
        *,
        template_key: str = "default",
        recipient: str | None = None,
        priority: str = "tx",
        locale: str = "ru",
        context_property: str | None = None,
        result_property: str = "notify_result",
    ) -> "RouteBuilder":
        """Отправка уведомления через NotificationGateway (Wave 8.3).

        В отличие от старого sugar (dispatch_action), теперь это полноценный
        DSL-процессор: ``NotifyProcessor`` обращается к gateway напрямую,
        пишет ``SendResult`` в property и поддерживает round-trip через
        ``to_spec()``.

        Args:
            channel: ``email|sms|slack|teams|telegram|webhook|express``.
            template_key: Имя шаблона в TemplateRegistry.
            recipient: Получатель. Если None — берётся из ``body['recipient']``.
            priority: ``tx`` или ``marketing``.
            locale: Локаль шаблона.
            context_property: Имя property с контекстом для рендера.
            result_property: Имя property для ``SendResult``.
        """
        from src.backend.dsl.engine.processors.notify import NotifyProcessor

        return self._add(
            NotifyProcessor(
                channel=channel,
                template_key=template_key,
                recipient=recipient,
                priority=priority,
                locale=locale,
                context_property=context_property,
                result_property=result_property,
            )
        )

    # web_search — перенесён в dsl.builders.converters.ConvertersMixin (Stage 2.1).

    # ── AI Extended ──

    # call_llm_with_fallback / cache / cache_write / guardrails /
    # semantic_route — перенесены в dsl.builders.ai_rpa.AIRPAMixin (Stage 2.2).

    # ── RPA (UiPath-style) ──

    # pdf_read / pdf_merge / word_read / word_write / excel_read — перенесены
    # в dsl.builders.converters.ConvertersMixin (Stage 2.1).

    def file_move(
        self, src: str | None = None, dst: str | None = None, *, mode: str = "copy"
    ) -> "RouteBuilder":
        """Copy/move/rename файлов."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.rpa",
            "FileMoveProcessor",
            src=src,
            dst=dst,
            mode=mode,
        )

    # archive / ocr / image_resize / regex / render_template — перенесены в
    # dsl.builders.converters.ConvertersMixin (Stage 2.1).
    # hash / encrypt / decrypt — перенесены в dsl.builders.converters.ConvertersMixin
    # (Stage 2.1 PoC). Доступны через MRO у RouteBuilder.

    def shell(
        self,
        command: str,
        *,
        args: list[str] | None = None,
        allowed_commands: list[str] | None = None,
    ) -> "RouteBuilder":
        """Shell-команда с whitelist и timeout."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.rpa",
            "ShellExecProcessor",
            command=command,
            args=args,
            allowed_commands=allowed_commands,
        )

    def email(self, to: str, subject: str, body_template: str) -> "RouteBuilder":
        """Compose + send email через SMTP."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.rpa",
            "EmailComposeProcessor",
            to=to,
            subject=subject,
            body_template=body_template,
        )

    # ── Framework Patterns (n8n, Benthos, Zapier) ──

    def switch(
        self,
        field: str,
        cases: dict[str, list[BaseProcessor]],
        *,
        default: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """n8n Switch — case/match роутинг по значению поля."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.patterns",
            "SwitchProcessor",
            field=field,
            cases=cases,
            default=default,
        )

    # merge / batch_window / deduplicate / format_text / debounce — перенесены
    # в dsl.builders.converters.ConvertersMixin (Stage 2.1).

    # ── Ergonomics (DSL v2) ──────────────────────────────

    # as_ — перенесён в dsl.builders.converters.ConvertersMixin (Stage 2.1).

    def on_error(
        self,
        *,
        action: str | None = None,
        processors: list[BaseProcessor] | None = None,
        dlq_stream: str = "dsl-dlq",
    ) -> "RouteBuilder":
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

        current = list(self._processors)
        self._processors.clear()
        wrapped = DeadLetterProcessor(
            processors=current + handler_procs, dlq_stream=dlq_stream
        )
        self._processors.append(wrapped)
        return self

    # filter_dispatch / pick / drop / batch_by_field / poll_and_aggregate —
    # перенесены в dsl.builders.converters.ConvertersMixin (Stage 2.1).

    # ── DSL v3: .require_* helpers ────────────────────────

    def require_header(self, name: str) -> "RouteBuilder":
        """DX-2: валидирует присутствие header. Fail route если отсутствует.

        Usage::
            .require_header("Authorization")
        """

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            if not exchange.in_message.headers.get(name):
                exchange.fail(f"Missing required header: {name}")

        return self._add(CallableProcessor(_check, name=f"require_header:{name}"))

    def require_bearer(self) -> "RouteBuilder":
        """DX-2: валидирует Bearer token в Authorization header."""

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            auth = exchange.in_message.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                exchange.fail("Missing or invalid Bearer token")
                return
            token = auth[7:].strip()
            if not token:
                exchange.fail("Empty Bearer token")
                return
            exchange.set_property("auth_token", token)

        return self._add(CallableProcessor(_check, name="require_bearer"))

    def require_auth(self) -> "RouteBuilder":
        """DX-2: валидирует API key или Bearer token."""

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            auth = exchange.in_message.headers.get("Authorization", "")
            api_key = exchange.in_message.headers.get("X-API-Key", "")
            if not auth and not api_key:
                exchange.fail(
                    "Authentication required (Authorization or X-API-Key header)"
                )
                return
            exchange.set_property("authenticated", True)

        return self._add(CallableProcessor(_check, name="require_auth"))

    def require_fields(self, *names: str) -> "RouteBuilder":
        """DX-2: валидирует что в body есть указанные поля.

        Usage::
            .require_fields("order_id", "customer_email")
        """
        required = tuple(names)

        async def _check(exchange: Exchange[Any], context: Any) -> None:
            body = exchange.in_message.body
            if not isinstance(body, dict):
                exchange.fail(f"Body must be dict to check fields: {list(required)}")
                return
            missing = [f for f in required if f not in body]
            if missing:
                exchange.fail(f"Missing required fields: {missing}")

        return self._add(
            CallableProcessor(_check, name=f"require_fields:{','.join(required)}")
        )

    # cache_response — перенесён в dsl.builders.converters.ConvertersMixin (Stage 2.1).

    # ── RPA terminal/desktop/mobile ──

    # citrix / terminal_3270 / appium_mobile / email_driven / keystroke_replay —
    # перенесены в dsl.builders.ai_rpa.AIRPAMixin (Stage 2.2).

    # ── AI-пайплайны для банка ──

    # kyc_aml_verify / antifraud_score / credit_scoring_rag / customer_chatbot /
    # appeal_ai / tx_categorize / findoc_ocr_llm — перенесены в
    # dsl.builders.ai_rpa.AIRPAMixin (Stage 2.2).

    # ── Generic (универсальные) ──

    def shadow_mode(self, processors: list[BaseProcessor]) -> "RouteBuilder":
        """Исполняет вложенную ветку в shadow-режиме (без side effects)."""
        from src.backend.dsl.engine.processors.generic import ShadowModeProcessor

        return self._add(ShadowModeProcessor(processors=processors))

    def bulkhead(
        self,
        name: str,
        limit: int,
        processors: list[BaseProcessor],
        *,
        wait: bool = True,
        timeout: float | None = None,
    ) -> "RouteBuilder":
        """Ограничивает concurrency на ветку — защита провайдера от перегрузки."""
        from src.backend.dsl.engine.processors.generic import BulkheadProcessor

        return self._add(
            BulkheadProcessor(
                name=name,
                limit=limit,
                processors=processors,
                wait=wait,
                timeout=timeout,
            )
        )

    def lineage(self, tag: str = "step") -> "RouteBuilder":
        """Записывает шаг в `_lineage` property (data governance)."""
        from src.backend.dsl.engine.processors.generic import LineageTrackerProcessor

        return self._add(LineageTrackerProcessor(tag=tag))

    def sse_source(
        self, url: str, event_types: list[str] | None = None
    ) -> "RouteBuilder":
        """Source-процессор для Server-Sent Events."""
        from src.backend.dsl.engine.processors.generic import SseSourceProcessor

        return self._add(SseSourceProcessor(url=url, event_types=event_types))

    def schema_validate(self, schema: dict[str, Any]) -> "RouteBuilder":
        """Валидация body по JSON Schema (Draft 2020-12)."""
        from src.backend.dsl.engine.processors.generic import SchemaValidateProcessor

        return self._add(SchemaValidateProcessor(schema=schema))

    def ab_test(
        self,
        variant_a: list[BaseProcessor],
        variant_b: list[BaseProcessor],
        *,
        split_percent: int = 50,
        key_fn: Callable[[Exchange[Any]], str] | None = None,
    ) -> "RouteBuilder":
        """Стабильная маршрутизация X% трафика на вариант B."""
        from src.backend.dsl.engine.processors.generic import AbTestRouterProcessor

        return self._add(
            AbTestRouterProcessor(
                variant_a=variant_a,
                variant_b=variant_b,
                split_percent=split_percent,
                key_fn=key_fn,
            )
        )

    def feature_flag_branch(
        self,
        flag: str,
        processors: list[BaseProcessor],
        *,
        resolver: Callable[[str], bool] | None = None,
    ) -> "RouteBuilder":
        """Выполняет ветку процессоров только при включённом feature flag.

        Не путать с ``feature_flag(name)`` (метаданная маршрута, отключает
        маршрут целиком). Здесь — DSL-step внутри pipeline.
        """
        from src.backend.dsl.engine.processors.generic import FeatureFlagGuardProcessor

        return self._add(
            FeatureFlagGuardProcessor(
                flag=flag, processors=processors, resolver=resolver
            )
        )

    # ── Build ──

    def build(self, *, validate_actions: bool = True) -> Pipeline:
        """Собирает Pipeline из накопленных процессоров. Финальный вызов в fluent-chain.

        Args:
            validate_actions: Если True (default), проверяет что все dispatch_action
                имена зарегистрированы в ActionHandlerRegistry. Raises ValueError
                с подсказкой схожих имён при опечатке.
        """
        if validate_actions:
            self._validate_action_names()
        return Pipeline(
            route_id=self.route_id,
            source=self.source,
            description=self.description,
            processors=list(self._processors),
            protocol=self._protocol,
            transport_config=self._transport_config,
            feature_flag=self._feature_flag,
        )

    def _validate_action_names(self) -> None:
        """DX-1: проверяет что все dispatch_action имена зарегистрированы.

        Raises ValueError с подсказкой schozih имён при опечатке.
        Вызывается в .build() (можно отключить validate_actions=False).
        """
        try:
            from src.backend.dsl.commands.registry import action_handler_registry

            available = set(action_handler_registry.list_actions())
        except (ImportError, AttributeError):
            return

        if not available:
            return

        action_names: list[str] = []
        for proc in self._processors:
            if type(proc).__name__ == "DispatchActionProcessor":
                action = getattr(proc, "action", None)
                if action and isinstance(action, str):
                    action_names.append(action)

        unknown = [name for name in action_names if name not in available]
        if not unknown:
            return

        import difflib

        suggestions: dict[str, list[str]] = {}
        for name in unknown:
            close = difflib.get_close_matches(name, available, n=3, cutoff=0.6)
            if close:
                suggestions[name] = close

        msg_parts = [f"Unknown action(s) in pipeline '{self.route_id}':"]
        for name in unknown:
            suggestion = suggestions.get(name)
            if suggestion:
                msg_parts.append(
                    f"  - '{name}' — did you mean: {', '.join(suggestion)}?"
                )
            else:
                msg_parts.append(f"  - '{name}'")
        raise ValueError("\n".join(msg_parts))

    # ── Streaming & expiration EIPs ──

    def expire(
        self,
        ttl_seconds: float,
        *,
        header_name: str = "x-created-at",
        drop_action: str = "fail",
    ) -> "RouteBuilder":
        """EIP Message Expiration: отбрасывает сообщения старше ``ttl_seconds``."""
        return self._add(
            MessageExpirationProcessor(
                ttl_seconds=ttl_seconds,
                header_name=header_name,
                drop_action=drop_action,
            )
        )

    def correlation_id(self, *, header: str = "x-correlation-id") -> "RouteBuilder":
        """EIP Correlation Identifier: проставляет/пропагирует correlation-id."""
        return self._add(CorrelationIdProcessor(header=header))

    def tumbling_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        size: int = 100,
        interval_seconds: float = 10.0,
        watermark_store: WatermarkStore | None = None,
    ) -> "RouteBuilder":
        """Streaming tumbling-окно фиксированного размера.

        Если ``watermark_store`` не задан и в ``app.state`` уже
        зарегистрирован durable store (W14.5), он подхватывается
        автоматически вместе с ``route_id`` маршрута. В тестах без
        composition root окно ведёт себя как in-memory.
        """
        store = watermark_store or get_watermark_store_optional()
        return self._add(
            TumblingWindowProcessor(
                sink=sink,
                size=size,
                interval_seconds=interval_seconds,
                watermark_store=store,
                route_id=self.route_id if store is not None else None,
            )
        )

    def sliding_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        window_seconds: float = 10.0,
        step_seconds: float = 2.0,
        watermark_store: WatermarkStore | None = None,
    ) -> "RouteBuilder":
        """Streaming sliding-окно с перекрытием.

        ``watermark_store`` подхватывается из ``app.state`` (W14.5),
        если не передан явно. См. :meth:`tumbling_window`.
        """
        store = watermark_store or get_watermark_store_optional()
        return self._add(
            SlidingWindowProcessor(
                sink=sink,
                window_seconds=window_seconds,
                step_seconds=step_seconds,
                watermark_store=store,
                route_id=self.route_id if store is not None else None,
            )
        )

    def session_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        gap_seconds: float = 30.0,
        watermark_store: WatermarkStore | None = None,
    ) -> "RouteBuilder":
        """Streaming session-окно (закрывается по паузе).

        ``watermark_store`` подхватывается из ``app.state`` (W14.5),
        если не передан явно. См. :meth:`tumbling_window`.
        """
        store = watermark_store or get_watermark_store_optional()
        return self._add(
            SessionWindowProcessor(
                sink=sink,
                gap_seconds=gap_seconds,
                watermark_store=store,
                route_id=self.route_id if store is not None else None,
            )
        )

    def group_by_key(
        self,
        key_path: str,
        sink: Callable[[dict[Any, list[Any]]], Any],
        *,
        window_seconds: float = 60.0,
    ) -> "RouteBuilder":
        """Группировка по ключу (jmespath) в пределах окна."""
        return self._add(
            GroupByKeyProcessor(
                sink=sink, key_path=key_path, window_seconds=window_seconds
            )
        )

    def validate_schema(
        self, subject: str, *, schema_loader: Any = None
    ) -> "RouteBuilder":
        """Валидация по схеме из реестра (JSON Schema / Avro / Protobuf)."""
        return self._add(
            SchemaRegistryValidator(subject=subject, schema_loader=schema_loader)
        )

    def reply_to(
        self,
        broker: Any,
        *,
        reply_to_header: str = "reply-to",
        correlation_header: str = "x-correlation-id",
    ) -> "RouteBuilder":
        """EIP Return Address: публикует ответ в очередь из reply-to заголовка."""
        return self._add(
            ReplyToProcessor(
                broker=broker,
                reply_to_header=reply_to_header,
                correlation_header=correlation_header,
            )
        )

    def exactly_once(
        self,
        storage: Any,
        *,
        id_header: str = "x-message-id",
        ttl_seconds: int = 86_400,
        namespace: str = "exactly-once",
    ) -> "RouteBuilder":
        """Exactly-once: dedup через storage по message-id."""
        return self._add(
            ExactlyOnceProcessor(
                storage=storage,
                id_header=id_header,
                ttl_seconds=ttl_seconds,
                namespace=namespace,
            )
        )

    def durable_fanout(self, broker: Any, subscribers: list[str]) -> "RouteBuilder":
        """EIP Durable Subscriber: fan-out к persistent-подписчикам."""
        return self._add(
            DurableSubscriberProcessor(broker=broker, subscribers=subscribers)
        )

    def purge_channel(
        self, broker: Any, channel: str, *, dry_run: bool = True
    ) -> "RouteBuilder":
        """Очистка очереди/стрима (admin-операция)."""
        return self._add(
            ChannelPurgerProcessor(broker=broker, channel=channel, dry_run=dry_run)
        )

    def sample(self, probability: float = 0.1) -> "RouteBuilder":
        """Вероятностный сэмплинг (A/B, canary, debug-sampling)."""
        return self._add(SamplingProcessor(probability=probability))

    # ── Enrichment (W28) ──

    # geoip — перенесён в dsl.builders.converters.ConvertersMixin (Stage 2.1).

    def jwt_sign(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        expires_in_seconds: int | None = 3600,
        output_property: str = "jwt",
    ) -> "RouteBuilder":
        """Подпись payload как JWT-токен (PyJWT)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.enrichment",
            "JwtSignProcessor",
            secret_key=secret_key,
            algorithm=algorithm,
            expires_in_seconds=expires_in_seconds,
            output_property=output_property,
        )

    def jwt_verify(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        header: str = "Authorization",
        output_property: str = "jwt_claims",
    ) -> "RouteBuilder":
        """Проверка JWT из заголовка; claims → property или fail."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.enrichment",
            "JwtVerifyProcessor",
            secret_key=secret_key,
            algorithm=algorithm,
            header=header,
            output_property=output_property,
        )

    # compress / decompress — перенесены в dsl.builders.converters.ConvertersMixin
    # (Stage 2.1 PoC). Доступны через MRO у RouteBuilder.

    def webhook_sign(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
    ) -> "RouteBuilder":
        """HMAC-подпись outgoing webhook'а."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.enrichment",
            "WebhookSignProcessor",
            secret=secret,
            header=header,
            algorithm=algorithm,
        )

    def webhook_verify(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
        prefix: str | None = None,
        on_mismatch: str = "fail",
    ) -> "RouteBuilder":
        """Верификация HMAC-подписи входящего webhook'а (timing-safe).

        ``on_mismatch="fail"`` (default) — fail pipeline; ``"warn"`` — лог
        предупреждения и установка ``webhook_signature_valid=False`` без
        остановки. ``prefix`` — опциональный схема-префикс (``"v1"``,
        ``"sha256"``), если подпись передаётся как ``v1=<hex>``.
        """
        return self._add_lazy(
            "src.backend.dsl.engine.processors.enrichment",
            "WebhookSignVerifyProcessor",
            secret=secret,
            header=header,
            algorithm=algorithm,
            prefix=prefix,
            on_mismatch=on_mismatch,
        )

    # jsonpath / convert_units / parse_ics — перенесены в
    # dsl.builders.converters.ConvertersMixin (Stage 2.1).

    def deadline(
        self, *, timeout_seconds: float = 30.0, fail_on_exceed: bool = True
    ) -> "RouteBuilder":
        """Установка дedline pipeline; downstream проверяет _deadline_at."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.enrichment",
            "DeadlineProcessor",
            timeout_seconds=timeout_seconds,
            fail_on_exceed=fail_on_exceed,
        )

    # ── Business (W28) ──

    def tenant_scope(
        self,
        *,
        header: str = "x-tenant-id",
        body_path: str | None = None,
        required: bool = True,
    ) -> "RouteBuilder":
        """Multi-tenancy scope: tenant_id из заголовка/body в Exchange."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "TenantScopeProcessor",
            header=header,
            body_path=body_path,
            required=required,
        )

    def cost_tracker(self) -> "RouteBuilder":
        """Инициализация cost-словаря в properties (LLM-токены, HTTP, DB, USD)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business", "CostTrackerProcessor"
        )

    def outbox(self, *, topic: str) -> "RouteBuilder":
        """Transactional Outbox: запись события в outbox-таблицу."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business", "OutboxProcessor", topic=topic
        )

    def mask(
        self, *, patterns: list[str] | None = None, replacement: str = "***"
    ) -> "RouteBuilder":
        """Маскирование PII/PCI в body (ИНН/СНИЛС/карта/email/телефон)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "DataMaskingProcessor",
            patterns=patterns,
            replacement=replacement,
        )

    def compliance_labels(self, *, labels: list[str]) -> "RouteBuilder":
        """Compliance-метки на Exchange (PII/PCI/FIN/GDPR)."""
        return self._add_lazy(
            "src.backend.dsl.engine.processors.business",
            "ComplianceLabelProcessor",
            labels=labels,
        )
