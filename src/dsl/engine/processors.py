import inspect
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange
from app.schemas.invocation import ActionCommandSchema

__all__ = (
    "ProcessorCallable",
    "BaseProcessor",
    "CallableProcessor",
    "SetHeaderProcessor",
    "SetPropertyProcessor",
    "DispatchActionProcessor",
    "TransformProcessor",
    "FilterProcessor",
    "EnrichProcessor",
    "LogProcessor",
    "ValidateProcessor",
    "MCPToolProcessor",
    "AgentGraphProcessor",
    "CDCProcessor",
)

ProcessorCallable = Callable[[Exchange[Any], ExecutionContext], Any | Awaitable[Any]]


class BaseProcessor(ABC):
    """
    Базовый класс для всех DSL-процессоров.

    Каждый процессор получает Exchange и ExecutionContext,
    может модифицировать сообщение, runtime-состояние и результат.
    """

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__

    @abstractmethod
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """
        Выполняет обработку Exchange.

        Args:
            exchange: Текущий Exchange.
            context: Контекст выполнения маршрута.
        """


class CallableProcessor(BaseProcessor):
    """
    Адаптер, превращающий обычную функцию или coroutine в процессор.
    """

    def __init__(self, func: ProcessorCallable, name: str | None = None) -> None:
        super().__init__(name=name or getattr(func, "__name__", None))
        self._func = func

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        result = self._func(exchange, context)
        if inspect.isawaitable(result):
            await result


class SetHeaderProcessor(BaseProcessor):
    """
    Процессор для установки заголовка входного сообщения.
    """

    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_header:{key}")
        self.key = key
        self.value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.in_message.set_header(self.key, self.value)


class SetPropertyProcessor(BaseProcessor):
    """
    Процессор для установки runtime-свойства Exchange.
    """

    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_property:{key}")
        self.key = key
        self.value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property(self.key, self.value)


class DispatchActionProcessor(BaseProcessor):
    """
    Процессор, который преобразует Exchange в ActionCommandSchema
    и исполняет команду через ActionHandlerRegistry.

    Это первый practical bridge между новым DSL и существующей
    action-командной моделью приложения.
    """

    def __init__(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "action_result",
    ) -> None:
        super().__init__(name=f"dispatch_action:{action}")
        self.action = action
        self.payload_factory = payload_factory
        self.result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self.payload_factory is not None:
            payload = self.payload_factory(exchange)
        else:
            body = exchange.in_message.body
            payload = body if isinstance(body, dict) else {}

        command = ActionCommandSchema(action=self.action, payload=payload)

        result = await context.action_registry.dispatch(command)

        exchange.set_property(self.result_property, result)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class TransformProcessor(BaseProcessor):
    """Маппинг полей body через jmespath-выражения.

    Пример:
        TransformProcessor(expression="data.items[0].name")
        → exchange.out_message.body = результат jmespath.search()
    """

    def __init__(self, expression: str, *, name: str | None = None) -> None:
        super().__init__(name=name or f"transform:{expression[:30]}")
        self.expression = expression

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import jmespath

        body = exchange.in_message.body
        result = jmespath.search(self.expression, body)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class FilterProcessor(BaseProcessor):
    """Условная маршрутизация — пропускает Exchange только при истинном условии.

    Если условие ложно, устанавливает свойство ``filtered=True``
    и прерывает дальнейшую обработку через ``exchange.stop()``.
    """

    def __init__(
        self,
        predicate: Callable[[Exchange[Any]], bool],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "filter")
        self._predicate = predicate

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if not self._predicate(exchange):
            exchange.set_property("filtered", True)
            exchange.stop()


class EnrichProcessor(BaseProcessor):
    """Обогащение Exchange данными из другого action.

    Вызывает action и сохраняет результат как свойство Exchange.
    """

    def __init__(
        self,
        action: str,
        *,
        payload_factory: Callable[[Exchange[Any]], dict[str, Any]] | None = None,
        result_property: str = "enrichment",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"enrich:{action}")
        self.action = action
        self.payload_factory = payload_factory
        self.result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self.payload_factory:
            payload = self.payload_factory(exchange)
        else:
            payload = {}

        command = ActionCommandSchema(action=self.action, payload=payload)
        result = await context.action_registry.dispatch(command)
        exchange.set_property(self.result_property, result)


class LogProcessor(BaseProcessor):
    """Логирует текущее состояние Exchange."""

    def __init__(self, *, level: str = "info", name: str | None = None) -> None:
        super().__init__(name=name or "log")
        self._level = level

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import logging

        logger = logging.getLogger("dsl.pipeline")
        log_fn = getattr(logger, self._level, logger.info)
        log_fn(
            "Exchange[route=%s]: body=%s, properties=%s",
            context.route_id,
            type(exchange.in_message.body).__name__,
            list(exchange.properties.keys()),
        )


class ValidateProcessor(BaseProcessor):
    """Валидация body через Pydantic-модель.

    Если валидация проваливается, устанавливает ошибку
    в Exchange и прерывает обработку.
    """

    def __init__(
        self,
        model: type,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"validate:{model.__name__}")
        self._model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from pydantic import ValidationError

        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.set_error(f"Ожидался dict, получен {type(body).__name__}")
            exchange.stop()
            return

        try:
            validated = self._model.model_validate(body)
            exchange.set_property("validated_payload", validated)
        except ValidationError as exc:
            exchange.set_error(str(exc))
            exchange.stop()


class MCPToolProcessor(BaseProcessor):
    """Вызывает внешний MCP tool из DSL pipeline.

    Позволяет маршруту обращаться к внешним MCP-серверам.
    """

    def __init__(
        self,
        tool_uri: str,
        tool_name: str,
        *,
        result_property: str = "mcp_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"mcp_tool:{tool_name}")
        self.tool_uri = tool_uri
        self.tool_name = tool_name
        self.result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import json as json_mod

        body = exchange.in_message.body
        payload = body if isinstance(body, dict) else {}

        try:
            from fastmcp import Client

            async with Client(self.tool_uri) as client:
                result = await client.call_tool(
                    self.tool_name,
                    arguments=payload,
                )
                exchange.set_property(self.result_property, result)
                exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
        except ImportError:
            exchange.set_error("fastmcp не установлен")
            exchange.stop()
        except Exception as exc:
            exchange.set_error(f"MCP tool error: {exc}")
            exchange.stop()


class AgentGraphProcessor(BaseProcessor):
    """Запускает LangGraph-агента внутри DSL pipeline.

    Агент получает body Exchange как промпт и может
    использовать указанные actions как tools.
    """

    def __init__(
        self,
        graph_name: str,
        tools: list[str],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"agent_graph:{graph_name}")
        self.graph_name = graph_name
        self.tools = tools

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        prompt = body if isinstance(body, str) else str(body)

        try:
            from app.services.ai_graph import build_and_run_agent

            result = await build_and_run_agent(
                prompt=prompt,
                tool_actions=self.tools,
            )
            exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
        except ImportError:
            exchange.set_error("langgraph не установлен")
            exchange.stop()
        except Exception as exc:
            exchange.set_error(f"Agent graph error: {exc}")
            exchange.stop()


class CDCProcessor(BaseProcessor):
    """Реагирует на CDC-события и маршрутизирует через DSL.

    Создаёт CDC-подписку при первом вызове и направляет
    изменения в target_action.
    """

    def __init__(
        self,
        profile: str,
        tables: list[str],
        target_action: str,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"cdc:{profile}")
        self.profile = profile
        self.tables = tables
        self.target_action = target_action
        self._subscribed = False

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if not self._subscribed:
            from app.infrastructure.clients.cdc import get_cdc_client

            client = get_cdc_client()
            sub_id = await client.subscribe(
                profile=self.profile,
                tables=self.tables,
                target_action=self.target_action,
            )
            self._subscribed = True
            exchange.set_property("cdc_subscription_id", sub_id)

        exchange.set_out(
            body={"status": "cdc_active", "profile": self.profile, "tables": self.tables},
            headers=dict(exchange.in_message.headers),
        )
