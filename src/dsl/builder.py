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
