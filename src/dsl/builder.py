from dataclasses import dataclass, field
from typing import Any, Callable

from app.dsl.adapters.types import ProtocolType, TransportConfig
from app.dsl.engine.exchange import Exchange
from app.dsl.engine.pipeline import Pipeline
from app.dsl.engine.processors import (
    AgentGraphProcessor,
    BaseProcessor,
    CallableProcessor,
    CDCProcessor,
    ChoiceProcessor,
    CircuitBreakerProcessor,
    ClaimCheckProcessor,
    DeadLetterProcessor,
    DispatchActionProcessor,
    EnrichProcessor,
    FallbackChainProcessor,
    FilterProcessor,
    IdempotentConsumerProcessor,
    LoadBalancerProcessor,
    LogProcessor,
    MCPToolProcessor,
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
    SetHeaderProcessor,
    SetPropertyProcessor,
    TransformProcessor,
    TryCatchProcessor,
    ValidateProcessor,
    WireTapProcessor,
    MessageTranslatorProcessor,
    DynamicRouterProcessor,
    ScatterGatherProcessor,
    ThrottlerProcessor,
    DelayProcessor,
    SplitterProcessor,
    AggregatorProcessor,
)
from app.dsl.engine.processors.streaming import (
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
class RouteBuilder:
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

    def _add(self, processor: BaseProcessor) -> "RouteBuilder":
        self._processors.append(processor)
        return self

    def _add_lazy(self, import_path: str, class_name: str, **kwargs: Any) -> "RouteBuilder":
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

    def process_fn(self, func: ProcessorCallable, *, name: str | None = None) -> "RouteBuilder":
        """Добавляет обычную функцию или coroutine как процессор.

        Функция принимает (exchange, context) и модифицирует exchange in-place.
        """
        return self._add(CallableProcessor(func=func, name=name))

    def include(self, other: Pipeline) -> "RouteBuilder":
        """Включает все процессоры из другого Pipeline (композиция)."""
        self._processors.extend(other.processors)
        return self

    # ── Core processors ──

    def set_header(self, key: str, value: Any) -> "RouteBuilder":
        """Устанавливает заголовок в in_message."""
        return self._add(SetHeaderProcessor(key=key, value=value))

    def set_property(self, key: str, value: Any) -> "RouteBuilder":
        """Устанавливает runtime-свойство Exchange."""
        return self._add(SetPropertyProcessor(key=key, value=value))

    def dispatch_action(
        self, action: str, *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """Вызывает зарегистрированный action (Camel Service Activator).

        Основной способ связи DSL с бизнес-логикой. Action ищется
        в ActionHandlerRegistry по имени (e.g., "orders.add").
        """
        return self._add(DispatchActionProcessor(
            action=action, payload_factory=payload_factory, result_property=result_property,
        ))

    def transform(self, expression: str) -> "RouteBuilder":
        """Трансформирует body через JMESPath-выражение."""
        return self._add(TransformProcessor(expression=expression))

    def filter(self, predicate: Callable[[Exchange[Any]], bool]) -> "RouteBuilder":
        """Фильтрует Exchange — останавливает, если predicate=False."""
        return self._add(FilterProcessor(predicate=predicate))

    def enrich(
        self, action: str, *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "enrichment",
    ) -> "RouteBuilder":
        return self._add(EnrichProcessor(
            action=action, payload_factory=payload_factory, result_property=result_property,
        ))

    def log(self, level: str = "info") -> "RouteBuilder":
        """Логирование текущего состояния Exchange (для отладки)."""
        return self._add(LogProcessor(level=level))

    def validate(self, model: type) -> "RouteBuilder":
        """Pydantic-валидация body; при ошибке Exchange останавливается."""
        return self._add(ValidateProcessor(model=model))

    # ── Integration processors ──

    def mcp_tool(self, uri: str, tool: str, *, result_property: str = "mcp_result") -> "RouteBuilder":
        """Вызов внешнего MCP tool."""
        return self._add(MCPToolProcessor(tool_uri=uri, tool_name=tool, result_property=result_property))

    def agent_graph(self, graph_name: str, tools: list[str]) -> "RouteBuilder":
        """Запуск LangGraph-агента."""
        return self._add(AgentGraphProcessor(graph_name=graph_name, tools=tools))

    def cdc(
        self, profile: str, tables: list[str], target_action: str, *,
        strategy: str = "polling",
        interval: float = 5.0,
        timestamp_column: str = "updated_at",
        batch_size: int = 100,
        channel: str | None = None,
    ) -> "RouteBuilder":
        """Change Data Capture — подписка на изменения в БД.

        strategy: polling (любая БД), listen_notify (PostgreSQL), logminer (Oracle).
        """
        return self._add(CDCProcessor(
            profile=profile, tables=tables, target_action=target_action,
            strategy=strategy, interval=interval,
            timestamp_column=timestamp_column, batch_size=batch_size,
            channel=channel,
        ))

    # ── Control flow ──

    def choice(
        self,
        when: list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
        otherwise: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Camel When/Otherwise: ветвление по предикатам."""
        return self._add(ChoiceProcessor(when=when, otherwise=otherwise))

    def do_try(
        self,
        try_processors: list[BaseProcessor],
        catch_processors: list[BaseProcessor] | None = None,
        finally_processors: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Camel Try/Catch/Finally: exception handling в pipeline."""
        return self._add(TryCatchProcessor(
            try_processors=try_processors,
            catch_processors=catch_processors,
            finally_processors=finally_processors,
        ))

    def retry(
        self, processors: list[BaseProcessor], *,
        max_attempts: int = 3, delay_seconds: float = 1.0, backoff: str = "exponential",
    ) -> "RouteBuilder":
        """Retry с backoff: повторяет процессоры при ошибке. backoff: fixed|exponential."""
        return self._add(RetryProcessor(
            processors=processors, max_attempts=max_attempts,
            delay_seconds=delay_seconds, backoff=backoff,
        ))

    def to_route(self, route_id: str, *, result_property: str = "sub_result") -> "RouteBuilder":
        """Вызов другого зарегистрированного DSL-маршрута."""
        return self._add(PipelineRefProcessor(route_id=route_id, result_property=result_property))

    def parallel(self, branches: dict[str, list[BaseProcessor]], *, strategy: str = "all") -> "RouteBuilder":
        """Параллельное выполнение именованных веток. strategy: all|first."""
        return self._add(ParallelProcessor(branches=branches, strategy=strategy))

    def saga(self, steps: list[SagaStep]) -> "RouteBuilder":
        """Saga-паттерн: последовательные шаги с компенсацией при ошибке."""
        return self._add(SagaProcessor(steps=steps))

    def dead_letter(self, processors: list[BaseProcessor], *, dlq_stream: str = "dsl-dlq") -> "RouteBuilder":
        """Dead Letter Channel: при ошибке — отправка в Redis stream."""
        return self._add(DeadLetterProcessor(processors=processors, dlq_stream=dlq_stream))

    def idempotent(self, key_expression: Callable[[Exchange[Any]], str], *, ttl_seconds: int = 86400) -> "RouteBuilder":
        """Идемпотентный consumer: дедупликация через Redis SET NX EX."""
        return self._add(IdempotentConsumerProcessor(key_expression=key_expression, ttl_seconds=ttl_seconds))

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

    def dynamic_route(self, route_expression: Callable[[Exchange[Any]], str]) -> "RouteBuilder":
        """Camel Dynamic Router: runtime-вычисление route_id."""
        return self._add(DynamicRouterProcessor(route_expression=route_expression))

    def scatter_gather(
        self, route_ids: list[str], *,
        aggregation: str = "merge", timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Camel Scatter-Gather: fan-out на N маршрутов + сборка результатов."""
        return self._add(ScatterGatherProcessor(
            route_ids=route_ids, aggregation=aggregation, timeout_seconds=timeout_seconds,
        ))

    def throttle(self, rate: float, *, burst: int = 1) -> "RouteBuilder":
        """Camel Throttler: rate-limit N сообщений/сек (token bucket)."""
        return self._add(ThrottlerProcessor(rate=rate, burst=burst))

    def delay(
        self, delay_ms: int | None = None, *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
    ) -> "RouteBuilder":
        """Camel Delay: задержка на N миллисекунд или до timestamp."""
        return self._add(DelayProcessor(delay_ms=delay_ms, scheduled_time_fn=scheduled_time_fn))

    def split(self, expression: str, processors: list[BaseProcessor]) -> "RouteBuilder":
        """Camel Splitter: разбиение массива на отдельные Exchange по JMESPath."""
        return self._add(SplitterProcessor(expression=expression, processors=processors))

    def aggregate(
        self,
        correlation_key: Callable[[Exchange[Any]], str], *,
        batch_size: int = 10, timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Camel Aggregator: собирает N Exchange по correlation_key в batch."""
        return self._add(AggregatorProcessor(
            correlation_key=correlation_key, batch_size=batch_size, timeout_seconds=timeout_seconds,
        ))

    def recipient_list(
        self,
        recipients_expression: Callable[[Exchange[Any]], list[str]], *,
        parallel: bool = True,
    ) -> "RouteBuilder":
        """Camel Recipient List: динамический fan-out на список маршрутов."""
        return self._add(RecipientListProcessor(recipients_expression=recipients_expression, parallel=parallel))

    # ── Camel EIP v2 ──

    def load_balance(
        self, targets: list[str], *,
        strategy: str = "round_robin",
        weights: list[float] | None = None,
        sticky_header: str | None = None,
    ) -> "RouteBuilder":
        """Camel Load Balancer: round_robin/random/weighted/sticky распределение."""
        return self._add(LoadBalancerProcessor(
            targets=targets, strategy=strategy, weights=weights, sticky_header=sticky_header,
        ))

    def circuit_breaker(
        self, processors: list[BaseProcessor], *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        fallback_processors: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Camel Circuit Breaker: fail-fast при повторных ошибках (CLOSED/OPEN/HALF_OPEN)."""
        return self._add(CircuitBreakerProcessor(
            processors=processors, failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout, fallback_processors=fallback_processors,
        ))

    def claim_check_in(self, *, store: str = "redis", ttl_seconds: int = 3600) -> "RouteBuilder":
        """Camel Claim Check (store): сохраняет body в Redis, body → {_claim_token: ...}."""
        return self._add(ClaimCheckProcessor(mode="store", store=store, ttl_seconds=ttl_seconds))

    def claim_check_out(self) -> "RouteBuilder":
        """Camel Claim Check (retrieve): восстанавливает body по _claim_token."""
        return self._add(ClaimCheckProcessor(mode="retrieve"))

    def normalize(self, target_schema: type | None = None) -> "RouteBuilder":
        """Camel Normalizer: автоопределение формата (XML/CSV/YAML/JSON) → canonical dict."""
        return self._add(NormalizerProcessor(target_schema=target_schema))

    def resequence(
        self,
        correlation_key: Callable[[Exchange[Any]], str], *,
        sequence_field: str = "seq",
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Camel Resequencer: восстановление порядка сообщений по sequence_field."""
        return self._add(ResequencerProcessor(
            correlation_key=correlation_key, sequence_field=sequence_field,
            batch_size=batch_size, timeout_seconds=timeout_seconds,
        ))

    def multicast(
        self, branches: list[list[BaseProcessor]], *,
        strategy: str = "all",
        stop_on_error: bool = False,
    ) -> "RouteBuilder":
        """Camel Multicast: fan-out на flat list процессор-групп + aggregation."""
        return self._add(MulticastProcessor(
            branches=branches, strategy=strategy, stop_on_error=stop_on_error,
        ))

    def loop(
        self, processors: list[BaseProcessor], *,
        count: int | None = None,
        until: Callable[[Exchange[Any]], bool] | None = None,
        max_iterations: int = 1000,
    ) -> "RouteBuilder":
        """Camel Loop — execute sub-processors N times or until condition."""
        return self._add_lazy("app.dsl.engine.processors.eip", "LoopProcessor",
                              processors=processors, count=count, until=until, max_iterations=max_iterations)

    def on_completion(
        self, processors: list[BaseProcessor], *,
        on_success_only: bool = False,
        on_failure_only: bool = False,
    ) -> "RouteBuilder":
        """Camel OnCompletion — run callback after pipeline finishes (like finally)."""
        return self._add_lazy("app.dsl.engine.processors.eip", "OnCompletionProcessor",
                              processors=processors, on_success_only=on_success_only, on_failure_only=on_failure_only)

    def sort(
        self, *,
        key_fn: Callable[[Any], Any] | None = None,
        key_field: str | None = None,
        reverse: bool = False,
    ) -> "RouteBuilder":
        """Camel Sort — sort list body by key function or field name."""
        return self._add_lazy("app.dsl.engine.processors.eip", "SortProcessor",
                              key_fn=key_fn, key_field=key_field, reverse=reverse)

    def timeout(
        self, processors: list[BaseProcessor], *,
        seconds: float = 30.0,
        fallback_processors: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Camel Timeout — wrap sub-processors with a time limit."""
        return self._add_lazy("app.dsl.engine.processors.eip", "TimeoutProcessor",
                              processors=processors, seconds=seconds, fallback_processors=fallback_processors)

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

    # ── Camel Components (source/sink) ──

    def http_call(
        self, url: str, *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        timeout: float = 30.0,
        result_property: str | None = None,
    ) -> "RouteBuilder":
        """HTTP client: GET/POST/PUT/DELETE с таймаутом и headers."""
        return self._add_lazy("app.dsl.engine.processors.components", "HttpCallProcessor",
                              url=url, method=method, headers=headers, auth_token=auth_token,
                              timeout=timeout, result_property=result_property)

    def db_query(self, sql: str, *, result_property: str = "db_result") -> "RouteBuilder":
        """SQL-запрос через SQLAlchemy (с валидацией: DDL/multi-statement запрещены)."""
        return self._add_lazy("app.dsl.engine.processors.components", "DatabaseQueryProcessor",
                              sql=sql, result_property=result_property)

    def read_file(self, path: str | None = None, *, binary: bool = False) -> "RouteBuilder":
        """Чтение локального файла в body (text или bytes)."""
        return self._add_lazy("app.dsl.engine.processors.components", "FileReadProcessor",
                              path=path, binary=binary)

    def write_file(self, path: str | None = None, *, format: str = "auto") -> "RouteBuilder":
        """Запись body в файл. format: auto|json|csv|text."""
        return self._add_lazy("app.dsl.engine.processors.components", "FileWriteProcessor",
                              path=path, format=format)

    def read_s3(self, bucket: str | None = None, key: str | None = None) -> "RouteBuilder":
        """Загрузка объекта из S3."""
        return self._add_lazy("app.dsl.engine.processors.components", "S3ReadProcessor",
                              bucket=bucket, key=key)

    def write_s3(self, bucket: str | None = None, key: str | None = None, *, content_type: str = "application/octet-stream") -> "RouteBuilder":
        """Выгрузка body в S3."""
        return self._add_lazy("app.dsl.engine.processors.components", "S3WriteProcessor",
                              bucket=bucket, key=key, content_type=content_type)

    def timer(self, *, interval_seconds: float | None = None, cron: str | None = None, max_fires: int | None = None) -> "RouteBuilder":
        """Scheduled event source: интервал или cron-выражение."""
        return self._add_lazy("app.dsl.engine.processors.components", "TimerProcessor",
                              interval_seconds=interval_seconds, cron=cron, max_fires=max_fires)

    def poll(self, source_action: str, *, payload: dict[str, Any] | None = None, result_property: str = "polled_data") -> "RouteBuilder":
        """Periodically вызывает action, результат → body."""
        return self._add_lazy("app.dsl.engine.processors.components", "PollingConsumerProcessor",
                              source_action=source_action, payload=payload, result_property=result_property)

    # ── Type Converters ──

    def convert(self, from_format: str, to_format: str) -> "RouteBuilder":
        """Универсальный конвертер: json↔yaml/xml/csv/msgpack/parquet/bson, html→json."""
        return self._add_lazy("app.dsl.engine.processors.converters", "ConvertProcessor",
                              from_format=from_format, to_format=to_format)

    # ── Scraping Pipeline ──

    def scrape(self, url: str | None = None, *, selectors: dict[str, str] | None = None, output_property: str = "scraped") -> "RouteBuilder":
        """Извлечение данных с URL через CSS-селекторы (с SSRF-защитой)."""
        return self._add_lazy("app.dsl.engine.processors.scraping", "ScrapeProcessor",
                              url=url, selectors=selectors, output_property=output_property)

    def paginate(self, *, next_selector: str = "a.next", item_selector: str | None = None, max_pages: int = 10, start_url: str | None = None) -> "RouteBuilder":
        """Multi-page crawling с защитой от циклов и лимитом страниц."""
        return self._add_lazy("app.dsl.engine.processors.scraping", "PaginateProcessor",
                              next_selector=next_selector, item_selector=item_selector, max_pages=max_pages, start_url=start_url)

    def api_proxy(self, base_url: str, *, method: str = "GET", path: str = "", timeout: float = 30.0) -> "RouteBuilder":
        """Прозрачный API proxy с request/response трансформацией."""
        return self._add_lazy("app.dsl.engine.processors.scraping", "ApiProxyProcessor",
                              base_url=base_url, method=method, path=path, timeout=timeout)

    # ── AI Pipeline ──

    def rag_search(self, query_field: str = "question", top_k: int = 5, namespace: str | None = None) -> "RouteBuilder":
        """RAG vector search: top-K ближайших документов по семантике."""
        return self._add_lazy("app.dsl.engine.processors", "VectorSearchProcessor",
                              query_field=query_field, top_k=top_k, namespace=namespace)

    def compose_prompt(self, template: str, context_property: str = "vector_results") -> "RouteBuilder":
        """Построение промпта из шаблона + контекста из properties."""
        return self._add_lazy("app.dsl.engine.processors", "PromptComposerProcessor",
                              template=template, context_property=context_property)

    def call_llm(self, provider: str | None = None, model: str | None = None) -> "RouteBuilder":
        """LLM chat-completion через ai_agent сервис (с PII-маскировкой)."""
        return self._add_lazy("app.dsl.engine.processors", "LLMCallProcessor",
                              provider=provider, model=model)

    def parse_llm_output(self, schema: type | None = None) -> "RouteBuilder":
        """Парсинг LLM-ответа в Pydantic-модель (с попыткой извлечь JSON)."""
        return self._add_lazy("app.dsl.engine.processors", "LLMParserProcessor", schema=schema)

    def token_budget(self, max_tokens: int = 4096) -> "RouteBuilder":
        """Ограничение по токенам (tiktoken) — обрезка текста до лимита."""
        return self._add_lazy("app.dsl.engine.processors", "TokenBudgetProcessor", max_tokens=max_tokens)

    def sanitize_pii(self) -> "RouteBuilder":
        """Маскирование PII (email/phone/СНИЛС/карт) перед LLM."""
        return self._add_lazy("app.dsl.engine.processors", "SanitizePIIProcessor")

    def restore_pii(self) -> "RouteBuilder":
        """Восстановление PII в ответе после LLM."""
        return self._add_lazy("app.dsl.engine.processors", "RestorePIIProcessor")

    def publish_event(self, channel: str) -> "RouteBuilder":
        """Публикация события через EventBus."""
        return self._add_lazy("app.dsl.engine.processors", "EventPublishProcessor", channel=channel)

    def load_memory(self, session_id_header: str = "X-Session-Id") -> "RouteBuilder":
        """Загрузка conversation/facts из AgentMemory (Redis)."""
        return self._add_lazy("app.dsl.engine.processors", "MemoryLoadProcessor",
                              session_id_header=session_id_header)

    def save_memory(self) -> "RouteBuilder":
        """Сохранение результата в AgentMemory."""
        return self._add_lazy("app.dsl.engine.processors", "MemorySaveProcessor")

    # ── Web Automation ──

    def navigate(self, url: str) -> "RouteBuilder":
        """Открыть URL в браузере (Playwright)."""
        return self._add_lazy("app.dsl.engine.processors.web", "NavigateProcessor", url=url)

    def click(self, url: str, selector: str) -> "RouteBuilder":
        """Клик по CSS-селектору."""
        return self._add_lazy("app.dsl.engine.processors.web", "ClickProcessor", url=url, selector=selector)

    def fill_form(self, url: str, fields: dict | None = None, submit: str | None = None) -> "RouteBuilder":
        """Заполнение формы по полям + опциональный submit."""
        return self._add_lazy("app.dsl.engine.processors.web", "FillFormProcessor",
                              url=url, fields=fields, submit=submit)

    def extract(self, selector: str, url: str | None = None, output_property: str = "extracted") -> "RouteBuilder":
        """Извлечение текста по CSS-селектору."""
        return self._add_lazy("app.dsl.engine.processors.web", "ExtractProcessor",
                              url=url, selector=selector, output_property=output_property)

    def screenshot(self, url: str | None = None) -> "RouteBuilder":
        """Скриншот страницы как bytes."""
        return self._add_lazy("app.dsl.engine.processors.web", "ScreenshotProcessor", url=url)

    def run_scenario(self, steps: list[dict] | None = None) -> "RouteBuilder":
        """Multi-step web сценарий (navigate/click/fill/extract)."""
        return self._add_lazy("app.dsl.engine.processors.web", "RunScenarioProcessor", steps=steps)

    # ── Data Quality ──

    def dq_check(self, rules: list[Any] | None = None, dataset: str = "default", fail_on_violation: bool = False) -> "RouteBuilder":
        """Проверка DQ-правил (not_null/range/regex) на body."""
        return self._add_lazy("app.dsl.engine.processors.dq_check", "DQCheckProcessor",
                              rules=rules, dataset=dataset, fail_on_violation=fail_on_violation)

    # ── Export & Notify ──

    def export(self, format: str = "csv", output_property: str = "export_data", title: str = "Report") -> "RouteBuilder":
        """Экспорт body (list[dict]) в CSV/Excel/PDF → bytes в property."""
        return self._add_lazy("app.dsl.engine.processors.export", "ExportProcessor",
                              format=format, output_property=output_property, title=title)

    def notify(self, channel: str = "email", to: str = "", subject: str = "", message: str = "") -> "RouteBuilder":
        """Отправка уведомления через notification_hub (email/telegram/webhook/express)."""
        return self.dispatch_action(f"notify.{channel}" if channel != "send" else "notify.send")

    # ── Search ──

    def web_search(self, query_field: str = "query", provider: str | None = None, output_property: str = "search_results") -> "RouteBuilder":
        """Web search через Perplexity/Tavily (search_providers)."""
        async def _search(exchange: Exchange[Any], context: Any) -> None:
            from app.infrastructure.clients.external.search_providers import get_web_search_service
            body = exchange.in_message.body
            query = body.get(query_field) if isinstance(body, dict) else str(body)
            svc = get_web_search_service()
            results = await svc.query(query, provider=provider)
            exchange.set_property(output_property, results)

        return self._add(CallableProcessor(_search, name=f"web_search:{query_field}"))

    # ── AI Extended ──

    def call_llm_with_fallback(self, providers: list[str], *, model: str = "default") -> "RouteBuilder":
        """LLM с fallback-цепочкой провайдеров."""
        return self._add_lazy("app.dsl.engine.processors.ai", "LLMFallbackProcessor",
                              providers=providers, model=model)

    def cache(self, key_fn: Callable[[Exchange[Any]], str], *, ttl: int = 3600) -> "RouteBuilder":
        """Redis-кеш: проверяет наличие по ключу, пропускает если есть."""
        return self._add_lazy("app.dsl.engine.processors.ai", "CacheProcessor",
                              key_fn=key_fn, ttl_seconds=ttl)

    def cache_write(self, key_fn: Callable[[Exchange[Any]], str], *, ttl: int = 3600) -> "RouteBuilder":
        """Redis-кеш: записывает результат после обработки."""
        return self._add_lazy("app.dsl.engine.processors.ai", "CacheWriteProcessor",
                              key_fn=key_fn, ttl_seconds=ttl)

    def guardrails(self, *, max_length: int = 10000, blocked_patterns: list[str] | None = None, required_fields: list[str] | None = None) -> "RouteBuilder":
        """Проверка LLM output на безопасность (длина, blocklist, required fields)."""
        return self._add_lazy("app.dsl.engine.processors.ai", "GuardrailsProcessor",
                              max_length=max_length, blocked_patterns=blocked_patterns, required_fields=required_fields)

    def semantic_route(
        self, intents: dict[str, str], *,
        default_route: str | None = None,
        query_field: str = "question",
        threshold: float = 0.5,
        namespace: str = "intents",
    ) -> "RouteBuilder":
        """Semantic routing — RAG-based intent detection → выбор маршрута."""
        return self._add_lazy("app.dsl.engine.processors.ai", "SemanticRouterProcessor",
                              intents=intents, default_route=default_route,
                              query_field=query_field, threshold=threshold, namespace=namespace)

    # ── RPA (UiPath-style) ──

    def pdf_read(self, *, extract_tables: bool = False) -> "RouteBuilder":
        """Извлечь текст и таблицы из PDF."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "PdfReadProcessor", extract_tables=extract_tables)

    def pdf_merge(self) -> "RouteBuilder":
        """Объединить несколько PDF (body = list[bytes])."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "PdfMergeProcessor")

    def word_read(self) -> "RouteBuilder":
        """Извлечь текст из .docx."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "WordReadProcessor")

    def word_write(self) -> "RouteBuilder":
        """Сгенерировать .docx из body."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "WordWriteProcessor")

    def excel_read(self, *, sheet_name: str | None = None) -> "RouteBuilder":
        """Прочитать Excel → list[dict]."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "ExcelReadProcessor", sheet_name=sheet_name)

    def file_move(self, src: str | None = None, dst: str | None = None, *, mode: str = "copy") -> "RouteBuilder":
        """Copy/move/rename файлов."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "FileMoveProcessor", src=src, dst=dst, mode=mode)

    def archive(self, *, mode: str = "extract", format: str = "zip") -> "RouteBuilder":
        """ZIP/TAR архивация/распаковка."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "ArchiveProcessor", mode=mode, format=format)

    def ocr(self, *, lang: str = "eng+rus") -> "RouteBuilder":
        """OCR — текст с изображений (pytesseract)."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "ImageOcrProcessor", lang=lang)

    def image_resize(self, *, width: int | None = None, height: int | None = None, output_format: str = "PNG") -> "RouteBuilder":
        """Ресайз/конвертация изображений."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "ImageResizeProcessor",
                              width=width, height=height, output_format=output_format)

    def regex(self, pattern: str, *, action: str = "extract", replacement: str = "") -> "RouteBuilder":
        """Regex extract/replace/match."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "RegexProcessor",
                              pattern=pattern, action=action, replacement=replacement)

    def render_template(self, template: str) -> "RouteBuilder":
        """Jinja2 рендеринг шаблона."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "TemplateRenderProcessor", template=template)

    def hash(self, *, algorithm: str = "sha256") -> "RouteBuilder":
        """Hash данных (sha256/md5/sha512)."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "HashProcessor", algorithm=algorithm)

    def encrypt(self, key: str) -> "RouteBuilder":
        """AES шифрование (Fernet)."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "EncryptProcessor", key=key)

    def decrypt(self, key: str) -> "RouteBuilder":
        """AES расшифровка (Fernet)."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "DecryptProcessor", key=key)

    def shell(self, command: str, *, args: list[str] | None = None, allowed_commands: list[str] | None = None) -> "RouteBuilder":
        """Shell-команда с whitelist и timeout."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "ShellExecProcessor",
                              command=command, args=args, allowed_commands=allowed_commands)

    def email(self, to: str, subject: str, body_template: str) -> "RouteBuilder":
        """Compose + send email через SMTP."""
        return self._add_lazy("app.dsl.engine.processors.rpa", "EmailComposeProcessor",
                              to=to, subject=subject, body_template=body_template)

    # ── Framework Patterns (n8n, Benthos, Zapier) ──

    def switch(
        self, field: str, cases: dict[str, list[BaseProcessor]], *,
        default: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """n8n Switch — case/match роутинг по значению поля."""
        return self._add_lazy("app.dsl.engine.processors.patterns", "SwitchProcessor",
                              field=field, cases=cases, default=default)

    def merge(self, properties: list[str], *, mode: str = "append") -> "RouteBuilder":
        """n8n Merge — объединение properties в body. mode: append/merge/zip."""
        return self._add_lazy("app.dsl.engine.processors.patterns", "MergeProcessor",
                              properties=properties, mode=mode)

    def batch_window(self, *, window_seconds: float = 60.0, max_size: int = 100) -> "RouteBuilder":
        """Benthos — time-window batching."""
        return self._add_lazy("app.dsl.engine.processors.patterns", "BatchWindowProcessor",
                              window_seconds=window_seconds, max_size=max_size)

    def deduplicate(
        self, key_fn: Callable[[Exchange[Any]], str], *,
        window_seconds: float = 60.0,
    ) -> "RouteBuilder":
        """Benthos — дедупликация в скользящем окне."""
        return self._add_lazy("app.dsl.engine.processors.patterns", "DeduplicateProcessor",
                              key_fn=key_fn, window_seconds=window_seconds)

    def format_text(self, template: str, *, output_property: str | None = None) -> "RouteBuilder":
        """Zapier Formatter — строковое форматирование из properties."""
        return self._add_lazy("app.dsl.engine.processors.patterns", "FormatterProcessor",
                              template=template, output_property=output_property)

    def debounce(
        self, key_fn: Callable[[Exchange[Any]], str], *,
        delay_seconds: float = 5.0,
    ) -> "RouteBuilder":
        """Zapier Debounce — пропускает повторы, только последнее событие."""
        return self._add_lazy("app.dsl.engine.processors.patterns", "DebounceProcessor",
                              key_fn=key_fn, delay_seconds=delay_seconds)

    # ── Ergonomics (DSL v2) ──────────────────────────────

    def as_(self, name: str) -> "RouteBuilder":
        """Называет результат последнего процессора — сохраняет out_message в property.

        Usage::

            .http_call("https://api/x").as_("response")
            .transform("response.data")
        """
        async def _capture(exchange: Exchange[Any], context: Any) -> None:
            body = (
                exchange.out_message.body
                if exchange.out_message
                else exchange.in_message.body
            )
            exchange.set_property(name, body)
        return self._add(CallableProcessor(_capture, name=f"as_:{name}"))

    def on_error(
        self, *,
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
            processors=current + handler_procs,
            dlq_stream=dlq_stream,
        )
        self._processors.append(wrapped)
        return self

    def filter_dispatch(
        self,
        predicate: Callable[[Exchange[Any]], bool],
        action: str,
    ) -> "RouteBuilder":
        """Shorthand: filter + dispatch_action в одном вызове."""
        return self.filter(predicate).dispatch_action(action)

    def pick(self, *fields: str) -> "RouteBuilder":
        """JMESPath shorthand: оставляет только указанные поля в body."""
        if not fields:
            return self
        expr = "{" + ",".join(f"{f}: {f}" for f in fields) + "}"
        return self.transform(expr)

    def drop(self, *fields: str) -> "RouteBuilder":
        """Убирает указанные поля из body (через process_fn).

        JMESPath не поддерживает exclusion, поэтому используется функция.
        """
        drop_set = set(fields)

        async def _drop(exchange: Exchange[Any], context: Any) -> None:
            body = exchange.in_message.body
            if isinstance(body, dict):
                new_body = {k: v for k, v in body.items() if k not in drop_set}
                exchange.set_out(body=new_body, headers=dict(exchange.in_message.headers))

        return self._add(CallableProcessor(_drop, name=f"drop:{','.join(fields)}"))

    def batch_by_field(
        self,
        field: str, *,
        batch_size: int = 100,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Composite macro: aggregate по значению поля с окном size+timeout.

        Usage: .batch_by_field("customer_id", batch_size=50)
        """
        return self.aggregate(
            correlation_key=lambda ex: str(
                ex.in_message.body.get(field) if isinstance(ex.in_message.body, dict) else ex.in_message.body
            ),
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
        )

    def poll_and_aggregate(
        self,
        source_action: str, *,
        interval_seconds: float = 60.0,
        batch_size: int = 100,
        correlation_field: str = "id",
    ) -> "RouteBuilder":
        """Composite macro: timer + poll + aggregate — готовый polling ETL pattern."""
        return (
            self
            .timer(interval_seconds=interval_seconds)
            .poll(source_action)
            .batch_by_field(correlation_field, batch_size=batch_size)
        )

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
                exchange.fail("Authentication required (Authorization or X-API-Key header)")
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
        return self._add(CallableProcessor(_check, name=f"require_fields:{','.join(required)}"))

    def cache_response(self, *, ttl: int = 300, key_field: str = "") -> "RouteBuilder":
        """DX-2: кеширует результат pipeline в Redis по hash(body).

        Args:
            ttl: Время жизни кеша в секундах.
            key_field: Опционально поле из body для вычисления ключа
                (иначе hash всего body).
        """
        def _key_fn(ex: Exchange[Any]) -> str:
            body = ex.in_message.body
            if key_field and isinstance(body, dict):
                val = body.get(key_field, "")
                return f"{ex.meta.route_id}:{val}"
            import hashlib
            import orjson
            data = orjson.dumps(body, default=str) if body is not None else b""
            return f"{ex.meta.route_id}:{hashlib.sha256(data).hexdigest()[:16]}"

        self.cache(_key_fn, ttl=ttl)
        return self.cache_write(_key_fn, ttl=ttl)

    # ── Banking protocols ──

    def swift_mt_parse(self, message_type: str = "auto") -> "RouteBuilder":
        """Парсит SWIFT MT-сообщение (MT103/MT202/MT940) в dict."""
        from app.dsl.engine.processors.banking import SwiftMTParserProcessor
        return self._add(SwiftMTParserProcessor(message_type=message_type))

    def swift_mx_build(self, schema: str, action: str = "banking.swift_mx.build") -> "RouteBuilder":
        """Формирует SWIFT MX (ISO 20022 XML)."""
        from app.dsl.engine.processors.banking import SwiftMXBuilderProcessor
        return self._add(SwiftMXBuilderProcessor(schema=schema, action=action))

    def iso20022_parse(self, namespace: str | None = None) -> "RouteBuilder":
        """Парсит ISO 20022 XML (pain.001, camt.053, pacs.008)."""
        from app.dsl.engine.processors.banking import Iso20022ParserProcessor
        return self._add(Iso20022ParserProcessor(namespace=namespace))

    def fix_message(self, mode: str = "parse") -> "RouteBuilder":
        """Парсер/билдер FIX-сообщений."""
        from app.dsl.engine.processors.banking import FixMessageProcessor
        return self._add(FixMessageProcessor(mode=mode))

    def edifact_parse(self) -> "RouteBuilder":
        """Парсит UN/EDIFACT сегменты (FINPAY, PAYMUL)."""
        from app.dsl.engine.processors.banking import EdifactParserProcessor
        return self._add(EdifactParserProcessor())

    def onec_exchange(
        self, operation: str, entity: str, action: str = "onec.invoke",
    ) -> "RouteBuilder":
        """Интеграция с 1С:Предприятие через OData/HTTP-сервисы."""
        from app.dsl.engine.processors.banking import OneCExchangeProcessor
        return self._add(OneCExchangeProcessor(operation=operation, entity=entity, action=action))

    # ── RPA для банковских приложений ──

    def citrix(self, operation: str, session_id: str) -> "RouteBuilder":
        """Citrix/RDP-сессия (launch/click/type/screenshot/close)."""
        from app.dsl.engine.processors.rpa_banking import CitrixSessionProcessor
        return self._add(CitrixSessionProcessor(operation=operation, session_id=session_id))

    def sap_gui(self, operation: str, transaction: str | None = None) -> "RouteBuilder":
        """SAP GUI Scripting (Windows-only)."""
        from app.dsl.engine.processors.rpa_banking import SapGuiProcessor
        return self._add(SapGuiProcessor(operation=operation, transaction=transaction))

    def terminal_3270(self, host: str, port: int = 23, action: str = "query") -> "RouteBuilder":
        """IBM 3270 терминал-эмулятор (мейнфрейм)."""
        from app.dsl.engine.processors.rpa_banking import TerminalEmulator3270Processor
        return self._add(TerminalEmulator3270Processor(host=host, port=port, action=action))

    def appium_mobile(
        self, platform: str, app_package: str, operation: str,
    ) -> "RouteBuilder":
        """Appium автоматизация мобильных приложений (android/ios)."""
        from app.dsl.engine.processors.rpa_banking import AppiumMobileProcessor
        return self._add(AppiumMobileProcessor(
            platform=platform, app_package=app_package, operation=operation,
        ))

    def email_driven(
        self,
        mailbox: str = "INBOX",
        subject_filter: str | None = None,
        extract: str = "body_table",
    ) -> "RouteBuilder":
        """IMAP → structured data pipeline."""
        from app.dsl.engine.processors.rpa_banking import EmailDrivenProcessor
        return self._add(EmailDrivenProcessor(
            mailbox=mailbox, subject_filter=subject_filter, extract=extract,
        ))

    def keystroke_replay(self, script_name: str) -> "RouteBuilder":
        """Воспроизведение записанного сценария клавиатуры/мыши."""
        from app.dsl.engine.processors.rpa_banking import KeystrokeReplayProcessor
        return self._add(KeystrokeReplayProcessor(script_name=script_name))

    def bank_statement_pdf(self, bank_format: str = "generic") -> "RouteBuilder":
        """Парсер PDF-выписок по счёту."""
        from app.dsl.engine.processors.rpa_banking import BankStatementPdfParserProcessor
        return self._add(BankStatementPdfParserProcessor(bank_format=bank_format))

    # ── AI-пайплайны для банка ──

    def kyc_aml_verify(self, jurisdiction: str = "ru") -> "RouteBuilder":
        """KYC/AML верификация клиента."""
        from app.dsl.engine.processors.ai_banking import KycAmlVerifyProcessor
        return self._add(KycAmlVerifyProcessor(jurisdiction=jurisdiction))

    def antifraud_score(self, model: str = "default") -> "RouteBuilder":
        """LLM-скоринг антифрода (поверх детерминистических правил)."""
        from app.dsl.engine.processors.ai_banking import AntiFraudScoreProcessor
        return self._add(AntiFraudScoreProcessor(model=model))

    def credit_scoring_rag(self, product: str = "retail") -> "RouteBuilder":
        """Кредитный скоринг через RAG."""
        from app.dsl.engine.processors.ai_banking import CreditScoringRagProcessor
        return self._add(CreditScoringRagProcessor(product=product))

    def customer_chatbot(self, channel: str = "web") -> "RouteBuilder":
        """Клиентский чат-бот (tool-use: balance, statement, faq, escalate)."""
        from app.dsl.engine.processors.ai_banking import CustomerChatbotProcessor
        return self._add(CustomerChatbotProcessor(channel=channel))

    def appeal_ai(self) -> "RouteBuilder":
        """Автоматическая обработка клиентских обращений."""
        from app.dsl.engine.processors.ai_banking import AppealProcessorAI
        return self._add(AppealProcessorAI())

    def tx_categorize(self, taxonomy: str = "mcc") -> "RouteBuilder":
        """Категоризация транзакций (MCC + merchant normalization)."""
        from app.dsl.engine.processors.ai_banking import TransactionCategorizerProcessor
        return self._add(TransactionCategorizerProcessor(taxonomy=taxonomy))

    def findoc_ocr_llm(self, doc_type: str = "invoice") -> "RouteBuilder":
        """OCR + LLM для финансовых документов."""
        from app.dsl.engine.processors.ai_banking import FinDocOcrLlmProcessor
        return self._add(FinDocOcrLlmProcessor(doc_type=doc_type))

    # ── Generic (универсальные) ──

    def shadow_mode(self, processors: list[BaseProcessor]) -> "RouteBuilder":
        """Исполняет вложенную ветку в shadow-режиме (без side effects)."""
        from app.dsl.engine.processors.generic import ShadowModeProcessor
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
        from app.dsl.engine.processors.generic import BulkheadProcessor
        return self._add(BulkheadProcessor(
            name=name, limit=limit, processors=processors, wait=wait, timeout=timeout,
        ))

    def lineage(self, tag: str = "step") -> "RouteBuilder":
        """Записывает шаг в `_lineage` property (data governance)."""
        from app.dsl.engine.processors.generic import LineageTrackerProcessor
        return self._add(LineageTrackerProcessor(tag=tag))

    def sse_source(self, url: str, event_types: list[str] | None = None) -> "RouteBuilder":
        """Source-процессор для Server-Sent Events."""
        from app.dsl.engine.processors.generic import SseSourceProcessor
        return self._add(SseSourceProcessor(url=url, event_types=event_types))

    def schema_validate(self, schema: dict[str, Any]) -> "RouteBuilder":
        """Валидация body по JSON Schema (Draft 2020-12)."""
        from app.dsl.engine.processors.generic import SchemaValidateProcessor
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
        from app.dsl.engine.processors.generic import AbTestRouterProcessor
        return self._add(AbTestRouterProcessor(
            variant_a=variant_a, variant_b=variant_b,
            split_percent=split_percent, key_fn=key_fn,
        ))

    def feature_flag(
        self,
        flag: str,
        processors: list[BaseProcessor],
        *,
        resolver: Callable[[str], bool] | None = None,
    ) -> "RouteBuilder":
        """Выполняет ветку только при включённом feature flag."""
        from app.dsl.engine.processors.generic import FeatureFlagGuardProcessor
        return self._add(FeatureFlagGuardProcessor(
            flag=flag, processors=processors, resolver=resolver,
        ))

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
            from app.dsl.commands.registry import action_handler_registry
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
                msg_parts.append(f"  - '{name}' — did you mean: {', '.join(suggestion)}?")
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
        self, sink: Callable[[list[Any]], Any], *, size: int = 100, interval_seconds: float = 10.0,
    ) -> "RouteBuilder":
        """Streaming tumbling-окно фиксированного размера."""
        return self._add(
            TumblingWindowProcessor(sink=sink, size=size, interval_seconds=interval_seconds)
        )

    def sliding_window(
        self, sink: Callable[[list[Any]], Any], *, window_seconds: float = 10.0, step_seconds: float = 2.0,
    ) -> "RouteBuilder":
        """Streaming sliding-окно с перекрытием."""
        return self._add(
            SlidingWindowProcessor(sink=sink, window_seconds=window_seconds, step_seconds=step_seconds)
        )

    def session_window(
        self, sink: Callable[[list[Any]], Any], *, gap_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Streaming session-окно (закрывается по паузе)."""
        return self._add(SessionWindowProcessor(sink=sink, gap_seconds=gap_seconds))

    def group_by_key(
        self, key_path: str, sink: Callable[[dict[Any, list[Any]]], Any], *, window_seconds: float = 60.0,
    ) -> "RouteBuilder":
        """Группировка по ключу (jmespath) в пределах окна."""
        return self._add(
            GroupByKeyProcessor(sink=sink, key_path=key_path, window_seconds=window_seconds)
        )

    def validate_schema(self, subject: str, *, schema_loader: Any = None) -> "RouteBuilder":
        """Валидация по схеме из реестра (JSON Schema / Avro / Protobuf)."""
        return self._add(SchemaRegistryValidator(subject=subject, schema_loader=schema_loader))

    def reply_to(
        self, broker: Any, *, reply_to_header: str = "reply-to", correlation_header: str = "x-correlation-id",
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
        self, storage: Any, *, id_header: str = "x-message-id", ttl_seconds: int = 86_400, namespace: str = "exactly-once",
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
        return self._add(DurableSubscriberProcessor(broker=broker, subscribers=subscribers))

    def purge_channel(self, broker: Any, channel: str, *, dry_run: bool = True) -> "RouteBuilder":
        """Очистка очереди/стрима (admin-операция)."""
        return self._add(ChannelPurgerProcessor(broker=broker, channel=channel, dry_run=dry_run))

    def sample(self, probability: float = 0.1) -> "RouteBuilder":
        """Вероятностный сэмплинг (A/B, canary, debug-sampling)."""
        return self._add(SamplingProcessor(probability=probability))
