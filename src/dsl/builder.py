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
    DeadLetterProcessor,
    DispatchActionProcessor,
    EnrichProcessor,
    FallbackChainProcessor,
    FilterProcessor,
    IdempotentConsumerProcessor,
    LogProcessor,
    MCPToolProcessor,
    ParallelProcessor,
    PipelineRefProcessor,
    ProcessorCallable,
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
    RecipientListProcessor,
)

__all__ = ("RouteBuilder",)


@dataclass(slots=True)
class RouteBuilder:
    """Fluent-builder для DSL-маршрутов.

    Пример:
        route = (
            RouteBuilder.from_(
                route_id="tech.send_email",
                source="internal:tech.send_email",
                description="Маршрут отправки письма",
            )
            .protocol(ProtocolType.rest)
            .set_header("x-route", "tech.send_email")
            .dispatch_action("tech.send_email")
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

    @classmethod
    def from_(
        cls, route_id: str, source: str, *, description: str | None = None
    ) -> "RouteBuilder":
        """
        Создает builder с источником маршрута.

        Args:
            route_id: Уникальный идентификатор маршрута.
            source: Источник маршрута.
            description: Описание маршрута.

        Returns:
            RouteBuilder: Новый builder.
        """
        return cls(route_id=route_id, source=source, description=description)

    def process(self, processor: BaseProcessor) -> "RouteBuilder":
        """
        Добавляет процессор в маршрут.

        Args:
            processor: Экземпляр процессора.

        Returns:
            RouteBuilder: Текущий builder.
        """
        self._processors.append(processor)
        return self

    def process_fn(
        self, func: ProcessorCallable, *, name: str | None = None
    ) -> "RouteBuilder":
        """
        Добавляет функцию/корутину как процессор.

        Args:
            func: Callable с сигнатурой (exchange, context).
            name: Опциональное имя процессора.

        Returns:
            RouteBuilder: Текущий builder.
        """
        self._processors.append(CallableProcessor(func=func, name=name))
        return self

    def set_header(self, key: str, value: Any) -> "RouteBuilder":
        """
        Добавляет шаг установки заголовка.

        Args:
            key: Имя заголовка.
            value: Значение заголовка.

        Returns:
            RouteBuilder: Текущий builder.
        """
        self._processors.append(SetHeaderProcessor(key=key, value=value))
        return self

    def set_property(self, key: str, value: Any) -> "RouteBuilder":
        """
        Добавляет шаг установки runtime-свойства.

        Args:
            key: Имя свойства.
            value: Значение свойства.

        Returns:
            RouteBuilder: Текущий builder.
        """
        self._processors.append(SetPropertyProcessor(key=key, value=value))
        return self

    def dispatch_action(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> "RouteBuilder":
        """
        Добавляет шаг dispatch action-команды через registry.

        Args:
            action: Уникальное имя action-команды.
            payload_factory: Кастомная сборка payload из Exchange.
            result_property: Имя свойства, куда сохранять результат.

        Returns:
            RouteBuilder: Текущий builder.
        """
        self._processors.append(
            DispatchActionProcessor(
                action=action,
                payload_factory=payload_factory,
                result_property=result_property,
            )
        )
        return self

    def to(self, processor: BaseProcessor) -> "RouteBuilder":
        """Alias для ``process()``, ближе к стилю DSL.

        Args:
            processor: Экземпляр процессора.

        Returns:
            Текущий builder.
        """
        return self.process(processor)

    def protocol(
        self, proto: ProtocolType
    ) -> "RouteBuilder":
        """Устанавливает протокол маршрута.

        Args:
            proto: Тип протокола из ``ProtocolType``.

        Returns:
            Текущий builder.
        """
        self._protocol = proto
        return self

    def transport(
        self, config: TransportConfig
    ) -> "RouteBuilder":
        """Устанавливает конфигурацию транспорта.

        Args:
            config: Параметры транспорта (endpoint, timeout
                и протокол-специфичные опции).

        Returns:
            Текущий builder.
        """
        self._transport_config = config
        return self

    def transform(self, expression: str) -> "RouteBuilder":
        """Добавляет шаг маппинга через jmespath."""
        self._processors.append(TransformProcessor(expression=expression))
        return self

    def filter(
        self, predicate: Callable[[Exchange[Any]], bool]
    ) -> "RouteBuilder":
        """Добавляет условную фильтрацию."""
        self._processors.append(FilterProcessor(predicate=predicate))
        return self

    def enrich(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "enrichment",
    ) -> "RouteBuilder":
        """Добавляет обогащение данными из другого action."""
        self._processors.append(
            EnrichProcessor(
                action=action,
                payload_factory=payload_factory,
                result_property=result_property,
            )
        )
        return self

    def log(self, level: str = "info") -> "RouteBuilder":
        """Добавляет логирование Exchange."""
        self._processors.append(LogProcessor(level=level))
        return self

    def validate(self, model: type) -> "RouteBuilder":
        """Добавляет валидацию body через Pydantic-модель."""
        self._processors.append(ValidateProcessor(model=model))
        return self

    def mcp_tool(
        self,
        uri: str,
        tool: str,
        *,
        result_property: str = "mcp_result",
    ) -> "RouteBuilder":
        """Добавляет вызов внешнего MCP tool."""
        self._processors.append(
            MCPToolProcessor(tool_uri=uri, tool_name=tool, result_property=result_property)
        )
        return self

    def agent_graph(
        self,
        graph_name: str,
        tools: list[str],
    ) -> "RouteBuilder":
        """Добавляет запуск LangGraph-агента с указанными tools."""
        self._processors.append(
            AgentGraphProcessor(graph_name=graph_name, tools=tools)
        )
        return self

    def cdc(
        self,
        profile: str,
        tables: list[str],
        target_action: str,
    ) -> "RouteBuilder":
        """Добавляет CDC-подписку на изменения в таблицах."""
        self._processors.append(
            CDCProcessor(profile=profile, tables=tables, target_action=target_action)
        )
        return self

    def choice(
        self,
        when: list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
        otherwise: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Добавляет условное ветвление When/Otherwise."""
        self._processors.append(
            ChoiceProcessor(when=when, otherwise=otherwise)
        )
        return self

    def do_try(
        self,
        try_processors: list[BaseProcessor],
        catch_processors: list[BaseProcessor] | None = None,
        finally_processors: list[BaseProcessor] | None = None,
    ) -> "RouteBuilder":
        """Добавляет Try/Catch/Finally блок."""
        self._processors.append(
            TryCatchProcessor(
                try_processors=try_processors,
                catch_processors=catch_processors,
                finally_processors=finally_processors,
            )
        )
        return self

    def retry(
        self,
        processors: list[BaseProcessor],
        *,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        backoff: str = "exponential",
    ) -> "RouteBuilder":
        """Добавляет повтор sub-pipeline с backoff."""
        self._processors.append(
            RetryProcessor(
                processors=processors,
                max_attempts=max_attempts,
                delay_seconds=delay_seconds,
                backoff=backoff,
            )
        )
        return self

    def to_route(
        self,
        route_id: str,
        *,
        result_property: str = "sub_result",
    ) -> "RouteBuilder":
        """Вызывает другой зарегистрированный DSL-маршрут."""
        self._processors.append(
            PipelineRefProcessor(route_id=route_id, result_property=result_property)
        )
        return self

    def parallel(
        self,
        branches: dict[str, list[BaseProcessor]],
        *,
        strategy: str = "all",
    ) -> "RouteBuilder":
        """Выполняет несколько веток параллельно."""
        self._processors.append(
            ParallelProcessor(branches=branches, strategy=strategy)
        )
        return self

    def saga(self, steps: list[SagaStep]) -> "RouteBuilder":
        """Добавляет Saga-паттерн с компенсациями."""
        self._processors.append(SagaProcessor(steps=steps))
        return self

    def dead_letter(
        self,
        processors: list[BaseProcessor],
        *,
        dlq_stream: str = "dsl-dlq",
    ) -> "RouteBuilder":
        """Оборачивает процессоры в Dead Letter Channel."""
        self._processors.append(
            DeadLetterProcessor(processors=processors, dlq_stream=dlq_stream)
        )
        return self

    def idempotent(
        self,
        key_expression: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 86400,
    ) -> "RouteBuilder":
        """Добавляет дедупликацию по ключу (Redis)."""
        self._processors.append(
            IdempotentConsumerProcessor(
                key_expression=key_expression, ttl_seconds=ttl_seconds
            )
        )
        return self

    def fallback(self, processors: list[BaseProcessor]) -> "RouteBuilder":
        """Добавляет цепочку fallback-процессоров."""
        self._processors.append(FallbackChainProcessor(processors=processors))
        return self

    def wire_tap(self, tap_processors: list[BaseProcessor]) -> "RouteBuilder":
        """Копирует Exchange в отдельный канал (не влияет на основной)."""
        self._processors.append(WireTapProcessor(tap_processors=tap_processors))
        return self

    def translate(self, from_format: str, to_format: str) -> "RouteBuilder":
        """Конвертация форматов (JSON↔XML, JSON↔CSV)."""
        self._processors.append(
            MessageTranslatorProcessor(from_format=from_format, to_format=to_format)
        )
        return self

    def dynamic_route(
        self, route_expression: Callable[[Exchange[Any]], str]
    ) -> "RouteBuilder":
        """Маршрутизация на основе runtime-выражения."""
        self._processors.append(DynamicRouterProcessor(route_expression=route_expression))
        return self

    def scatter_gather(
        self,
        route_ids: list[str],
        *,
        aggregation: str = "merge",
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Fan-out на N маршрутов → сборка результатов."""
        self._processors.append(
            ScatterGatherProcessor(
                route_ids=route_ids,
                aggregation=aggregation,
                timeout_seconds=timeout_seconds,
            )
        )
        return self

    def throttle(self, rate: float, *, burst: int = 1) -> "RouteBuilder":
        """Rate-limit: N сообщений в секунду."""
        self._processors.append(ThrottlerProcessor(rate=rate, burst=burst))
        return self

    def delay(
        self,
        delay_ms: int | None = None,
        *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
    ) -> "RouteBuilder":
        """Задержка обработки на N мс или до timestamp."""
        self._processors.append(
            DelayProcessor(delay_ms=delay_ms, scheduled_time_fn=scheduled_time_fn)
        )
        return self

    def split(
        self, expression: str, processors: list[BaseProcessor]
    ) -> "RouteBuilder":
        """Разбивает массив на элементы → обработка каждого."""
        self._processors.append(
            SplitterProcessor(expression=expression, processors=processors)
        )
        return self

    def aggregate(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Собирает N Exchange по ключу корреляции."""
        self._processors.append(
            AggregatorProcessor(
                correlation_key=correlation_key,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
            )
        )
        return self

    def recipient_list(
        self,
        recipients_expression: Callable[[Exchange[Any]], list[str]],
        *,
        parallel: bool = True,
    ) -> "RouteBuilder":
        """Отправка на динамический список маршрутов."""
        self._processors.append(
            RecipientListProcessor(
                recipients_expression=recipients_expression, parallel=parallel
            )
        )
        return self

    def feature_flag(self, name: str) -> "RouteBuilder":
        """Защищает маршрут feature-флагом.

        Если флаг ``name`` находится в ``disabled_feature_flags``
        (runtime_state), маршрут вернёт ошибку при попытке
        выполнения.

        Args:
            name: Уникальное имя feature-флага.

        Returns:
            Текущий builder.
        """
        self._feature_flag = name
        return self

    # ────────────── AI Pipeline Methods ──────────────

    def rag_search(
        self,
        query_field: str = "question",
        top_k: int = 5,
        namespace: str | None = None,
    ) -> "RouteBuilder":
        """Семантический поиск в RAG vector store."""
        from app.dsl.engine.processors import VectorSearchProcessor

        self._processors.append(
            VectorSearchProcessor(
                query_field=query_field, top_k=top_k, namespace=namespace
            )
        )
        return self

    def compose_prompt(
        self,
        template: str,
        context_property: str = "vector_results",
    ) -> "RouteBuilder":
        """Строит промпт из шаблона + контекст из properties."""
        from app.dsl.engine.processors import PromptComposerProcessor

        self._processors.append(
            PromptComposerProcessor(
                template=template, context_property=context_property
            )
        )
        return self

    def call_llm(
        self,
        provider: str | None = None,
        model: str | None = None,
    ) -> "RouteBuilder":
        """Вызов LLM с PII-маскировкой и fallback."""
        from app.dsl.engine.processors import LLMCallProcessor

        self._processors.append(
            LLMCallProcessor(provider=provider, model=model)
        )
        return self

    def parse_llm_output(self, schema: type | None = None) -> "RouteBuilder":
        """Парсит ответ LLM в JSON/Pydantic."""
        from app.dsl.engine.processors import LLMParserProcessor

        self._processors.append(LLMParserProcessor(schema=schema))
        return self

    def token_budget(self, max_tokens: int = 4096) -> "RouteBuilder":
        """Обрезает вход по token budget перед LLM."""
        from app.dsl.engine.processors import TokenBudgetProcessor

        self._processors.append(TokenBudgetProcessor(max_tokens=max_tokens))
        return self

    def sanitize_pii(self) -> "RouteBuilder":
        """Маскирует PII в body."""
        from app.dsl.engine.processors import SanitizePIIProcessor

        self._processors.append(SanitizePIIProcessor())
        return self

    def restore_pii(self) -> "RouteBuilder":
        """Восстанавливает замаскированные PII."""
        from app.dsl.engine.processors import RestorePIIProcessor

        self._processors.append(RestorePIIProcessor())
        return self

    def publish_event(self, channel: str) -> "RouteBuilder":
        """Публикует событие в EventBus."""
        from app.dsl.engine.processors import EventPublishProcessor

        self._processors.append(EventPublishProcessor(channel=channel))
        return self

    def load_memory(self, session_id_header: str = "X-Session-Id") -> "RouteBuilder":
        """Загружает agent memory из Redis."""
        from app.dsl.engine.processors import MemoryLoadProcessor

        self._processors.append(
            MemoryLoadProcessor(session_id_header=session_id_header)
        )
        return self

    def save_memory(self) -> "RouteBuilder":
        """Сохраняет результат в agent memory."""
        from app.dsl.engine.processors import MemorySaveProcessor

        self._processors.append(MemorySaveProcessor())
        return self

    def include(self, other: Pipeline) -> "RouteBuilder":
        """Копирует процессоры из другого Pipeline (composition)."""
        self._processors.extend(other.processors)
        return self

    # ────────────── Web Automation Methods ──────────────

    def navigate(self, url: str) -> "RouteBuilder":
        """Открывает URL в браузере."""
        from app.dsl.engine.processors.web import NavigateProcessor
        self._processors.append(NavigateProcessor(url=url))
        return self

    def click(self, url: str, selector: str) -> "RouteBuilder":
        """Кликает по CSS-селектору."""
        from app.dsl.engine.processors.web import ClickProcessor
        self._processors.append(ClickProcessor(url=url, selector=selector))
        return self

    def fill_form(self, url: str, fields: dict | None = None, submit: str | None = None) -> "RouteBuilder":
        """Заполняет форму на странице."""
        from app.dsl.engine.processors.web import FillFormProcessor
        self._processors.append(FillFormProcessor(url=url, fields=fields, submit=submit))
        return self

    def extract(self, selector: str, url: str | None = None, output_property: str = "extracted") -> "RouteBuilder":
        """Извлекает текст по CSS-селектору."""
        from app.dsl.engine.processors.web import ExtractProcessor
        self._processors.append(ExtractProcessor(url=url, selector=selector, output_property=output_property))
        return self

    def screenshot(self, url: str | None = None) -> "RouteBuilder":
        """Скриншот страницы."""
        from app.dsl.engine.processors.web import ScreenshotProcessor
        self._processors.append(ScreenshotProcessor(url=url))
        return self

    def run_scenario(self, steps: list[dict] | None = None) -> "RouteBuilder":
        """Выполняет multi-step web сценарий."""
        from app.dsl.engine.processors.web import RunScenarioProcessor
        self._processors.append(RunScenarioProcessor(steps=steps))
        return self

    # ────────────── Search Methods ──────────────

    def web_search(self, query_field: str = "query", provider: str | None = None, output_property: str = "search_results") -> "RouteBuilder":
        """Web-поиск через Perplexity/Tavily."""
        from app.dsl.engine.processors.base import CallableProcessor

        async def _search(exchange, context):
            from app.infrastructure.clients.search_providers import get_web_search_service
            body = exchange.in_message.body
            query = body.get(query_field) if isinstance(body, dict) else str(body)
            svc = get_web_search_service()
            results = await svc.query(query, provider=provider)
            exchange.set_property(output_property, results)

        self._processors.append(CallableProcessor(_search, name=f"web_search:{query_field}"))
        return self

    def export(self, format: str = "csv", output_property: str = "export_data", title: str = "Report") -> "RouteBuilder":
        """Экспорт body (list[dict]) в Excel/CSV/PDF. Результат в properties."""
        from app.dsl.engine.processors.export import ExportProcessor
        self._processors.append(ExportProcessor(format=format, output_property=output_property, title=title))
        return self

    def build(self) -> Pipeline:
        """Собирает Pipeline из накопленных шагов.

        Returns:
            Готовый маршрут DSL.
        """
        return Pipeline(
            route_id=self.route_id,
            source=self.source,
            description=self.description,
            processors=list(self._processors),
            protocol=self._protocol,
            transport_config=self._transport_config,
            feature_flag=self._feature_flag,
        )
