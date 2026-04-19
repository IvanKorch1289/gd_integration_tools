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
        return self._add(processor)

    def to(self, processor: BaseProcessor) -> "RouteBuilder":
        return self._add(processor)

    def process_fn(self, func: ProcessorCallable, *, name: str | None = None) -> "RouteBuilder":
        return self._add(CallableProcessor(func=func, name=name))

    def include(self, other: Pipeline) -> "RouteBuilder":
        self._processors.extend(other.processors)
        return self

    # ── Core processors ──

    def set_header(self, key: str, value: Any) -> "RouteBuilder":
        return self._add(SetHeaderProcessor(key=key, value=value))

    def set_property(self, key: str, value: Any) -> "RouteBuilder":
        return self._add(SetPropertyProcessor(key=key, value=value))

    def dispatch_action(
        self, action: str, *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        return self._add(DispatchActionProcessor(
            action=action, payload_factory=payload_factory, result_property=result_property,
        ))

    def transform(self, expression: str) -> "RouteBuilder":
        return self._add(TransformProcessor(expression=expression))

    def filter(self, predicate: Callable[[Exchange[Any]], bool]) -> "RouteBuilder":
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
        return self._add(LogProcessor(level=level))

    def validate(self, model: type) -> "RouteBuilder":
        return self._add(ValidateProcessor(model=model))

    # ── Integration processors ──

    def mcp_tool(self, uri: str, tool: str, *, result_property: str = "mcp_result") -> "RouteBuilder":
        return self._add(MCPToolProcessor(tool_uri=uri, tool_name=tool, result_property=result_property))

    def agent_graph(self, graph_name: str, tools: list[str]) -> "RouteBuilder":
        return self._add(AgentGraphProcessor(graph_name=graph_name, tools=tools))

    def cdc(self, profile: str, tables: list[str], target_action: str) -> "RouteBuilder":
        return self._add(CDCProcessor(profile=profile, tables=tables, target_action=target_action))

    # ── Control flow ──

    def choice(
        self,
        when: list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
        otherwise: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        return self._add(ChoiceProcessor(when=when, otherwise=otherwise))

    def do_try(
        self,
        try_processors: list[BaseProcessor],
        catch_processors: list[BaseProcessor] | None = None,
        finally_processors: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        return self._add(TryCatchProcessor(
            try_processors=try_processors,
            catch_processors=catch_processors,
            finally_processors=finally_processors,
        ))

    def retry(
        self, processors: list[BaseProcessor], *,
        max_attempts: int = 3, delay_seconds: float = 1.0, backoff: str = "exponential",
    ) -> "RouteBuilder":
        return self._add(RetryProcessor(
            processors=processors, max_attempts=max_attempts,
            delay_seconds=delay_seconds, backoff=backoff,
        ))

    def to_route(self, route_id: str, *, result_property: str = "sub_result") -> "RouteBuilder":
        return self._add(PipelineRefProcessor(route_id=route_id, result_property=result_property))

    def parallel(self, branches: dict[str, list[BaseProcessor]], *, strategy: str = "all") -> "RouteBuilder":
        return self._add(ParallelProcessor(branches=branches, strategy=strategy))

    def saga(self, steps: list[SagaStep]) -> "RouteBuilder":
        return self._add(SagaProcessor(steps=steps))

    def dead_letter(self, processors: list[BaseProcessor], *, dlq_stream: str = "dsl-dlq") -> "RouteBuilder":
        return self._add(DeadLetterProcessor(processors=processors, dlq_stream=dlq_stream))

    def idempotent(self, key_expression: Callable[[Exchange[Any]], str], *, ttl_seconds: int = 86400) -> "RouteBuilder":
        return self._add(IdempotentConsumerProcessor(key_expression=key_expression, ttl_seconds=ttl_seconds))

    def fallback(self, processors: list[BaseProcessor]) -> "RouteBuilder":
        return self._add(FallbackChainProcessor(processors=processors))

    def wire_tap(self, tap_processors: list[BaseProcessor]) -> "RouteBuilder":
        return self._add(WireTapProcessor(tap_processors=tap_processors))

    # ── EIP processors ──

    def translate(self, from_format: str, to_format: str) -> "RouteBuilder":
        return self._add(MessageTranslatorProcessor(from_format=from_format, to_format=to_format))

    def dynamic_route(self, route_expression: Callable[[Exchange[Any]], str]) -> "RouteBuilder":
        return self._add(DynamicRouterProcessor(route_expression=route_expression))

    def scatter_gather(
        self, route_ids: list[str], *,
        aggregation: str = "merge", timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        return self._add(ScatterGatherProcessor(
            route_ids=route_ids, aggregation=aggregation, timeout_seconds=timeout_seconds,
        ))

    def throttle(self, rate: float, *, burst: int = 1) -> "RouteBuilder":
        return self._add(ThrottlerProcessor(rate=rate, burst=burst))

    def delay(
        self, delay_ms: int | None = None, *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
    ) -> "RouteBuilder":
        return self._add(DelayProcessor(delay_ms=delay_ms, scheduled_time_fn=scheduled_time_fn))

    def split(self, expression: str, processors: list[BaseProcessor]) -> "RouteBuilder":
        return self._add(SplitterProcessor(expression=expression, processors=processors))

    def aggregate(
        self,
        correlation_key: Callable[[Exchange[Any]], str], *,
        batch_size: int = 10, timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        return self._add(AggregatorProcessor(
            correlation_key=correlation_key, batch_size=batch_size, timeout_seconds=timeout_seconds,
        ))

    def recipient_list(
        self,
        recipients_expression: Callable[[Exchange[Any]], list[str]], *,
        parallel: bool = True,
    ) -> "RouteBuilder":
        return self._add(RecipientListProcessor(recipients_expression=recipients_expression, parallel=parallel))

    # ── Camel EIP v2 ──

    def load_balance(
        self, targets: list[str], *,
        strategy: str = "round_robin",
        weights: list[float] | None = None,
        sticky_header: str | None = None,
    ) -> "RouteBuilder":
        return self._add(LoadBalancerProcessor(
            targets=targets, strategy=strategy, weights=weights, sticky_header=sticky_header,
        ))

    def circuit_breaker(
        self, processors: list[BaseProcessor], *,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        fallback_processors: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        return self._add(CircuitBreakerProcessor(
            processors=processors, failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout, fallback_processors=fallback_processors,
        ))

    def claim_check_in(self, *, store: str = "redis", ttl_seconds: int = 3600) -> "RouteBuilder":
        return self._add(ClaimCheckProcessor(mode="store", store=store, ttl_seconds=ttl_seconds))

    def claim_check_out(self) -> "RouteBuilder":
        return self._add(ClaimCheckProcessor(mode="retrieve"))

    def normalize(self, target_schema: type | None = None) -> "RouteBuilder":
        return self._add(NormalizerProcessor(target_schema=target_schema))

    def resequence(
        self,
        correlation_key: Callable[[Exchange[Any]], str], *,
        sequence_field: str = "seq",
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        return self._add(ResequencerProcessor(
            correlation_key=correlation_key, sequence_field=sequence_field,
            batch_size=batch_size, timeout_seconds=timeout_seconds,
        ))

    def multicast(
        self, branches: list[list[BaseProcessor]], *,
        strategy: str = "all",
        stop_on_error: bool = False,
    ) -> "RouteBuilder":
        return self._add(MulticastProcessor(
            branches=branches, strategy=strategy, stop_on_error=stop_on_error,
        ))

    # ── Config ──

    def protocol(self, proto: ProtocolType) -> "RouteBuilder":
        self._protocol = proto
        return self

    def transport(self, config: TransportConfig) -> "RouteBuilder":
        self._transport_config = config
        return self

    def feature_flag(self, name: str) -> "RouteBuilder":
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
        return self._add_lazy("app.dsl.engine.processors.components", "HttpCallProcessor",
                              url=url, method=method, headers=headers, auth_token=auth_token,
                              timeout=timeout, result_property=result_property)

    def db_query(self, sql: str, *, result_property: str = "db_result") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.components", "DatabaseQueryProcessor",
                              sql=sql, result_property=result_property)

    def read_file(self, path: str | None = None, *, binary: bool = False) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.components", "FileReadProcessor",
                              path=path, binary=binary)

    def write_file(self, path: str | None = None, *, format: str = "auto") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.components", "FileWriteProcessor",
                              path=path, format=format)

    def read_s3(self, bucket: str | None = None, key: str | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.components", "S3ReadProcessor",
                              bucket=bucket, key=key)

    def write_s3(self, bucket: str | None = None, key: str | None = None, *, content_type: str = "application/octet-stream") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.components", "S3WriteProcessor",
                              bucket=bucket, key=key, content_type=content_type)

    def timer(self, *, interval_seconds: float | None = None, cron: str | None = None, max_fires: int | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.components", "TimerProcessor",
                              interval_seconds=interval_seconds, cron=cron, max_fires=max_fires)

    def poll(self, source_action: str, *, payload: dict[str, Any] | None = None, result_property: str = "polled_data") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.components", "PollingConsumerProcessor",
                              source_action=source_action, payload=payload, result_property=result_property)

    # ── Type Converters ──

    def convert(self, from_format: str, to_format: str) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.converters", "ConvertProcessor",
                              from_format=from_format, to_format=to_format)

    # ── Scraping Pipeline ──

    def scrape(self, url: str | None = None, *, selectors: dict[str, str] | None = None, output_property: str = "scraped") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.scraping", "ScrapeProcessor",
                              url=url, selectors=selectors, output_property=output_property)

    def paginate(self, *, next_selector: str = "a.next", item_selector: str | None = None, max_pages: int = 10, start_url: str | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.scraping", "PaginateProcessor",
                              next_selector=next_selector, item_selector=item_selector, max_pages=max_pages, start_url=start_url)

    def api_proxy(self, base_url: str, *, method: str = "GET", path: str = "", timeout: float = 30.0) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.scraping", "ApiProxyProcessor",
                              base_url=base_url, method=method, path=path, timeout=timeout)

    # ── AI Pipeline ──

    def rag_search(self, query_field: str = "question", top_k: int = 5, namespace: str | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "VectorSearchProcessor",
                              query_field=query_field, top_k=top_k, namespace=namespace)

    def compose_prompt(self, template: str, context_property: str = "vector_results") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "PromptComposerProcessor",
                              template=template, context_property=context_property)

    def call_llm(self, provider: str | None = None, model: str | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "LLMCallProcessor",
                              provider=provider, model=model)

    def parse_llm_output(self, schema: type | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "LLMParserProcessor", schema=schema)

    def token_budget(self, max_tokens: int = 4096) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "TokenBudgetProcessor", max_tokens=max_tokens)

    def sanitize_pii(self) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "SanitizePIIProcessor")

    def restore_pii(self) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "RestorePIIProcessor")

    def publish_event(self, channel: str) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "EventPublishProcessor", channel=channel)

    def load_memory(self, session_id_header: str = "X-Session-Id") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "MemoryLoadProcessor",
                              session_id_header=session_id_header)

    def save_memory(self) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors", "MemorySaveProcessor")

    # ── Web Automation ──

    def navigate(self, url: str) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.web", "NavigateProcessor", url=url)

    def click(self, url: str, selector: str) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.web", "ClickProcessor", url=url, selector=selector)

    def fill_form(self, url: str, fields: dict | None = None, submit: str | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.web", "FillFormProcessor",
                              url=url, fields=fields, submit=submit)

    def extract(self, selector: str, url: str | None = None, output_property: str = "extracted") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.web", "ExtractProcessor",
                              url=url, selector=selector, output_property=output_property)

    def screenshot(self, url: str | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.web", "ScreenshotProcessor", url=url)

    def run_scenario(self, steps: list[dict] | None = None) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.web", "RunScenarioProcessor", steps=steps)

    # ── Data Quality ──

    def dq_check(self, rules: list[Any] | None = None, dataset: str = "default", fail_on_violation: bool = False) -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.dq_check", "DQCheckProcessor",
                              rules=rules, dataset=dataset, fail_on_violation=fail_on_violation)

    # ── Export & Notify ──

    def export(self, format: str = "csv", output_property: str = "export_data", title: str = "Report") -> "RouteBuilder":
        return self._add_lazy("app.dsl.engine.processors.export", "ExportProcessor",
                              format=format, output_property=output_property, title=title)

    def notify(self, channel: str = "email", to: str = "", subject: str = "", message: str = "") -> "RouteBuilder":
        return self.dispatch_action(f"notify.{channel}" if channel != "send" else "notify.send")

    # ── Search ──

    def web_search(self, query_field: str = "query", provider: str | None = None, output_property: str = "search_results") -> "RouteBuilder":
        async def _search(exchange: Exchange[Any], context: Any) -> None:
            from app.infrastructure.clients.search_providers import get_web_search_service
            body = exchange.in_message.body
            query = body.get(query_field) if isinstance(body, dict) else str(body)
            svc = get_web_search_service()
            results = await svc.query(query, provider=provider)
            exchange.set_property(output_property, results)

        return self._add(CallableProcessor(_search, name=f"web_search:{query_field}"))

    # ── Build ──

    def build(self) -> Pipeline:
        return Pipeline(
            route_id=self.route_id,
            source=self.source,
            description=self.description,
            processors=list(self._processors),
            protocol=self._protocol,
            transport_config=self._transport_config,
            feature_flag=self._feature_flag,
        )
