import asyncio
import inspect
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
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
    "ChoiceProcessor",
    "TryCatchProcessor",
    "RetryProcessor",
    "PipelineRefProcessor",
    "ParallelProcessor",
    "SagaStep",
    "SagaProcessor",
    "DeadLetterProcessor",
    "IdempotentConsumerProcessor",
    "FallbackChainProcessor",
    "WireTapProcessor",
    "MessageTranslatorProcessor",
    "DynamicRouterProcessor",
    "ScatterGatherProcessor",
    "ThrottlerProcessor",
    "DelayProcessor",
    "SplitterProcessor",
    "AggregatorProcessor",
    "RecipientListProcessor",
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


# ---------------------------------------------------------------------------
#  Control-flow процессоры
# ---------------------------------------------------------------------------

_cf_logger = logging.getLogger("dsl.control_flow")


class ChoiceProcessor(BaseProcessor):
    """Условное ветвление When/Otherwise.

    Проверяет предикаты по порядку. Выполняет процессоры
    первой подходящей ветки. Если ни одна не подошла —
    выполняет ``otherwise``.

    Пример::

        ChoiceProcessor(
            when=[
                (lambda ex: ex.in_message.body.get("status") == "ok",
                 [DispatchActionProcessor("orders.update")]),
            ],
            otherwise=[LogProcessor(level="warning")],
        )
    """

    def __init__(
        self,
        when: list[tuple[Callable[[Exchange[Any]], bool], list[BaseProcessor]]],
        otherwise: list[BaseProcessor] | None = None,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "choice")
        self._when = when
        self._otherwise = otherwise or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        for predicate, branch_processors in self._when:
            if predicate(exchange):
                for proc in branch_processors:
                    if exchange.status == ExchangeStatus.failed or exchange.stopped:
                        break
                    await proc.process(exchange, context)
                return

        for proc in self._otherwise:
            if exchange.status == ExchangeStatus.failed or exchange.stopped:
                break
            await proc.process(exchange, context)


class TryCatchProcessor(BaseProcessor):
    """Try/Catch/Finally внутри DSL pipeline.

    Выполняет ``try_processors``. При ошибке — записывает
    исключение в ``exchange.properties["caught_error"]``
    и выполняет ``catch_processors``. ``finally_processors``
    выполняются всегда.
    """

    def __init__(
        self,
        try_processors: list[BaseProcessor],
        catch_processors: list[BaseProcessor] | None = None,
        finally_processors: list[BaseProcessor] | None = None,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "try_catch")
        self._try = try_processors
        self._catch = catch_processors or []
        self._finally = finally_processors or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        caught = False
        try:
            for proc in self._try:
                if exchange.status == ExchangeStatus.failed or exchange.stopped:
                    break
                await proc.process(exchange, context)
        except Exception as exc:
            caught = True
            exchange.set_property("caught_error", str(exc))
            # Сброс статуса failed для catch-обработки
            if exchange.status == ExchangeStatus.failed:
                exchange.status = ExchangeStatus.processing
                exchange.error = None
            for proc in self._catch:
                if exchange.stopped:
                    break
                await proc.process(exchange, context)

        if not caught and exchange.status == ExchangeStatus.failed:
            exchange.set_property("caught_error", exchange.error or "unknown")
            exchange.status = ExchangeStatus.processing
            exchange.error = None
            for proc in self._catch:
                if exchange.stopped:
                    break
                await proc.process(exchange, context)

        for proc in self._finally:
            if exchange.stopped:
                break
            try:
                await proc.process(exchange, context)
            except Exception as exc:
                _cf_logger.error("Finally processor error: %s", exc)


class RetryProcessor(BaseProcessor):
    """Повторяет sub-pipeline с настраиваемым backoff.

    Args:
        processors: Процессоры для повторного выполнения.
        max_attempts: Максимальное число попыток.
        delay_seconds: Базовая задержка.
        backoff: ``"fixed"`` или ``"exponential"``.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        backoff: str = "exponential",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"retry({max_attempts})")
        self._processors = processors
        self._max_attempts = max_attempts
        self._delay = delay_seconds
        self._backoff = backoff

    def _get_delay(self, attempt: int) -> float:
        if self._backoff == "exponential":
            return self._delay * (2 ** attempt)
        return self._delay

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        last_error: str | None = None

        for attempt in range(self._max_attempts):
            # Сброс состояния для повторной попытки
            if attempt > 0:
                exchange.status = ExchangeStatus.processing
                exchange.error = None
                exchange.properties.pop("_stopped", None)

            failed = False
            for proc in self._processors:
                if exchange.status == ExchangeStatus.failed or exchange.stopped:
                    failed = True
                    break
                try:
                    await proc.process(exchange, context)
                except Exception as exc:
                    exchange.fail(str(exc))
                    failed = True
                    break

            if exchange.status == ExchangeStatus.failed:
                failed = True

            if not failed:
                return

            last_error = exchange.error
            _cf_logger.warning(
                "Retry attempt %d/%d for '%s' failed: %s",
                attempt + 1,
                self._max_attempts,
                self.name,
                last_error,
            )

            if attempt < self._max_attempts - 1:
                await asyncio.sleep(self._get_delay(attempt))

        exchange.fail(f"All {self._max_attempts} attempts failed. Last: {last_error}")


class PipelineRefProcessor(BaseProcessor):
    """Вызывает другой зарегистрированный DSL-маршрут.

    Передаёт body текущего Exchange как вход, сохраняет
    результат в property.
    """

    def __init__(
        self,
        route_id: str,
        *,
        result_property: str = "sub_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"pipeline_ref:{route_id}")
        self._route_id = route_id
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.dsl.commands.registry import route_registry
        from app.dsl.engine.execution_engine import ExecutionEngine

        sub_pipeline = route_registry.get(self._route_id)
        engine = ExecutionEngine()
        sub_exchange = await engine.execute(
            sub_pipeline,
            body=exchange.in_message.body,
            headers=dict(exchange.in_message.headers),
            context=context,
        )

        if sub_exchange.status == ExchangeStatus.failed:
            exchange.fail(f"Sub-pipeline '{self._route_id}' failed: {sub_exchange.error}")
            return

        result = (
            sub_exchange.out_message.body
            if sub_exchange.out_message
            else sub_exchange.in_message.body
        )
        exchange.set_property(self._result_property, result)


class ParallelProcessor(BaseProcessor):
    """Выполняет несколько веток параллельно.

    Каждая ветка получает копию body. Результаты
    собираются в ``exchange.properties["parallel_results"]``.

    Args:
        branches: Словарь {имя: [процессоры]}.
        strategy: ``"all"`` — ждать все; ``"first"`` — первый успех.
    """

    def __init__(
        self,
        branches: dict[str, list[BaseProcessor]],
        *,
        strategy: str = "all",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "parallel")
        self._branches = branches
        self._strategy = strategy

    async def _run_branch(
        self,
        branch_name: str,
        processors: list[BaseProcessor],
        body: Any,
        headers: dict[str, Any],
        context: ExecutionContext,
    ) -> tuple[str, Any, str | None]:
        branch_exchange = Exchange(
            in_message=Message(body=body, headers=dict(headers))
        )
        branch_exchange.status = ExchangeStatus.processing

        for proc in processors:
            if branch_exchange.status == ExchangeStatus.failed or branch_exchange.stopped:
                break
            try:
                await proc.process(branch_exchange, context)
            except Exception as exc:
                branch_exchange.fail(str(exc))
                break

        result = (
            branch_exchange.out_message.body
            if branch_exchange.out_message
            else branch_exchange.in_message.body
        )
        return branch_name, result, branch_exchange.error

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        headers = exchange.in_message.headers

        tasks = [
            self._run_branch(name, procs, body, headers, context)
            for name, procs in self._branches.items()
        ]

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}

        if self._strategy == "first":
            done, pending = await asyncio.wait(
                [asyncio.create_task(t) for t in tasks],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                name, result, error = task.result()
                if error is None:
                    results[name] = result
                else:
                    errors[name] = error
        else:
            for coro_result in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(coro_result, Exception):
                    errors["_exception"] = str(coro_result)
                else:
                    name, result, error = coro_result
                    if error is None:
                        results[name] = result
                    else:
                        errors[name] = error

        exchange.set_property("parallel_results", results)
        if errors:
            exchange.set_property("parallel_errors", errors)


@dataclass
class SagaStep:
    """Шаг саги: forward-действие + компенсация при откате."""
    forward: BaseProcessor
    compensate: BaseProcessor | None = None


class SagaProcessor(BaseProcessor):
    """Saga-паттерн: выполняет шаги последовательно с откатом.

    Если шаг ``N`` падает — запускает компенсации шагов
    ``N-1, N-2, ..., 0`` в обратном порядке.
    """

    def __init__(
        self,
        steps: list[SagaStep],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"saga({len(steps)} steps)")
        self._steps = steps

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        completed_steps: list[SagaStep] = []

        for i, step in enumerate(self._steps):
            try:
                await step.forward.process(exchange, context)

                if exchange.status == ExchangeStatus.failed:
                    raise RuntimeError(exchange.error or f"Step {i} failed")

                completed_steps.append(step)
            except Exception as exc:
                _cf_logger.error("Saga step %d failed: %s. Compensating...", i, exc)
                exchange.set_property("saga_failed_step", i)
                exchange.set_property("saga_error", str(exc))

                for comp_step in reversed(completed_steps):
                    if comp_step.compensate is not None:
                        try:
                            exchange.status = ExchangeStatus.processing
                            exchange.error = None
                            await comp_step.compensate.process(exchange, context)
                        except Exception as comp_exc:
                            _cf_logger.error(
                                "Saga compensation failed: %s", comp_exc
                            )

                exchange.fail(f"Saga failed at step {i}: {exc}")
                return

        exchange.set_property("saga_completed", True)


# ---------------------------------------------------------------------------
#  Enterprise Integration Patterns
# ---------------------------------------------------------------------------

_eip_logger = logging.getLogger("dsl.eip")


class DeadLetterProcessor(BaseProcessor):
    """Dead Letter Channel — направляет упавшие Exchange в DLQ.

    Оборачивает sub-pipeline. При неуспехе сохраняет Exchange
    в DLQ-хранилище (Redis stream) с полным контекстом ошибки.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        dlq_stream: str = "dsl-dlq",
        max_retries: int = 0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "dead_letter")
        self._processors = processors
        self._dlq_stream = dlq_stream
        self._max_retries = max_retries

    async def _send_to_dlq(self, exchange: Exchange[Any]) -> None:
        try:
            from app.infrastructure.clients.redis import redis_client

            dlq_entry = {
                "exchange_id": exchange.meta.exchange_id,
                "route_id": exchange.meta.route_id or "",
                "correlation_id": exchange.meta.correlation_id,
                "error": exchange.error or "unknown",
                "body": str(exchange.in_message.body)[:4096],
                "properties": str(exchange.properties)[:2048],
                "timestamp": exchange.meta.created_at.isoformat(),
            }
            await redis_client.add_to_stream(
                stream_name=self._dlq_stream,
                data=dlq_entry,
            )
            _eip_logger.info(
                "Exchange %s sent to DLQ stream '%s'",
                exchange.meta.exchange_id,
                self._dlq_stream,
            )
        except Exception as dlq_exc:
            _eip_logger.error("Failed to send to DLQ: %s", dlq_exc)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        for proc in self._processors:
            if exchange.status == ExchangeStatus.failed or exchange.stopped:
                break
            try:
                await proc.process(exchange, context)
            except Exception as exc:
                exchange.fail(str(exc))
                break

        if exchange.status == ExchangeStatus.failed:
            await self._send_to_dlq(exchange)


class IdempotentConsumerProcessor(BaseProcessor):
    """Idempotent Consumer — предотвращает повторную обработку.

    Использует Redis SET NX EX для дедупликации по ключу.
    Если сообщение уже обработано, Exchange останавливается.
    """

    def __init__(
        self,
        key_expression: Callable[[Exchange[Any]], str],
        *,
        ttl_seconds: int = 86400,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "idempotent_consumer")
        self._key_expr = key_expression
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            from app.infrastructure.clients.redis import redis_client

            dedup_key = f"idempotent:{self._key_expr(exchange)}"
            is_new = await redis_client.set_if_not_exists(
                key=dedup_key, value="1", ttl=self._ttl
            )
            if not is_new:
                _eip_logger.debug(
                    "Duplicate message filtered: key=%s", dedup_key
                )
                exchange.set_property("idempotent_duplicate", True)
                exchange.stop()
                return
        except Exception as exc:
            _eip_logger.warning(
                "Idempotent check failed (proceeding): %s", exc
            )


class FallbackChainProcessor(BaseProcessor):
    """Fallback Chain — последовательно пробует процессоры.

    Выполняет первый процессор. При ошибке — следующий.
    Останавливается на первом успешном. Если все провалились —
    Exchange завершается ошибкой последнего.
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"fallback_chain({len(processors)})")
        self._processors = processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
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
                _eip_logger.debug(
                    "Fallback %d (%s) failed: %s", i, proc.name, exc
                )

        exchange.fail(f"All fallbacks exhausted. Last error: {last_error}")


class WireTapProcessor(BaseProcessor):
    """Wire Tap — копирует Exchange в отдельный канал.

    Не влияет на основной поток. Полезно для логирования,
    аудита, отладки.

    Args:
        tap_processors: Процессоры, обрабатывающие копию Exchange.
    """

    def __init__(
        self,
        tap_processors: list[BaseProcessor],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "wire_tap")
        self._tap_processors = tap_processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        tap_exchange = Exchange(
            in_message=Message(
                body=exchange.in_message.body,
                headers=dict(exchange.in_message.headers),
            )
        )
        tap_exchange.meta.route_id = exchange.meta.route_id
        tap_exchange.meta.correlation_id = exchange.meta.correlation_id
        tap_exchange.properties = dict(exchange.properties)
        tap_exchange.status = ExchangeStatus.processing

        async def _run_tap() -> None:
            for proc in self._tap_processors:
                if tap_exchange.status == ExchangeStatus.failed:
                    break
                try:
                    await proc.process(tap_exchange, context)
                except Exception as exc:
                    _eip_logger.debug("Wire tap processor error: %s", exc)

        asyncio.create_task(_run_tap())


# ---------------------------------------------------------------------------
#  Apache Camel-inspired процессоры
# ---------------------------------------------------------------------------

_camel_logger = logging.getLogger("dsl.camel")


class MessageTranslatorProcessor(BaseProcessor):
    """Конвертация форматов: JSON↔XML, JSON↔CSV.

    Работает через подключаемые конвертеры. По умолчанию
    поддерживает json→xml, xml→json, dict→csv, csv→dict.
    """

    def __init__(
        self,
        from_format: str,
        to_format: str,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"translate:{from_format}→{to_format}")
        self._from = from_format
        self._to = to_format

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        converted = self._convert(body)
        exchange.set_out(body=converted, headers=dict(exchange.in_message.headers))

    def _convert(self, body: Any) -> Any:
        key = f"{self._from}→{self._to}"

        if key == "json→xml" or key == "dict→xml":
            return self._dict_to_xml(body if isinstance(body, dict) else {})

        if key == "xml→json" or key == "xml→dict":
            return self._xml_to_dict(body if isinstance(body, str) else str(body))

        if key == "dict→csv" or key == "json→csv":
            return self._dict_list_to_csv(body if isinstance(body, list) else [body])

        if key == "csv→dict" or key == "csv→json":
            return self._csv_to_dict_list(body if isinstance(body, str) else str(body))

        return body

    @staticmethod
    def _dict_to_xml(data: dict, root_tag: str = "root") -> str:
        parts = [f"<{root_tag}>"]
        for k, v in data.items():
            parts.append(f"  <{k}>{v}</{k}>")
        parts.append(f"</{root_tag}>")
        return "\n".join(parts)

    @staticmethod
    def _xml_to_dict(xml_str: str) -> dict[str, str]:
        import re as _re
        result: dict[str, str] = {}
        for match in _re.finditer(r"<(\w+)>([^<]*)</\1>", xml_str):
            result[match.group(1)] = match.group(2)
        return result

    @staticmethod
    def _dict_list_to_csv(data: list[dict]) -> str:
        if not data:
            return ""
        headers = list(data[0].keys())
        lines = [",".join(headers)]
        for row in data:
            lines.append(",".join(str(row.get(h, "")) for h in headers))
        return "\n".join(lines)

    @staticmethod
    def _csv_to_dict_list(csv_str: str) -> list[dict[str, str]]:
        lines = csv_str.strip().split("\n")
        if len(lines) < 2:
            return []
        headers = [h.strip() for h in lines[0].split(",")]
        return [
            dict(zip(headers, [v.strip() for v in line.split(",")]))
            for line in lines[1:]
        ]


class DynamicRouterProcessor(BaseProcessor):
    """Маршрутизация на основе runtime-выражения.

    Вычисляет route_id из Exchange, затем делегирует
    выполнение соответствующему DSL-маршруту.
    """

    def __init__(
        self,
        route_expression: Callable[[Exchange[Any]], str],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "dynamic_router")
        self._expr = route_expression

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.dsl.commands.registry import route_registry
        from app.dsl.engine.execution_engine import ExecutionEngine

        target_route_id = self._expr(exchange)
        if not route_registry.is_registered(target_route_id):
            exchange.fail(f"Dynamic route '{target_route_id}' not found")
            return

        pipeline = route_registry.get(target_route_id)
        engine = ExecutionEngine()
        sub = await engine.execute(
            pipeline,
            body=exchange.in_message.body,
            headers=dict(exchange.in_message.headers),
            context=context,
        )

        if sub.status == ExchangeStatus.failed:
            exchange.fail(f"Dynamic route '{target_route_id}' failed: {sub.error}")
            return

        result = sub.out_message.body if sub.out_message else sub.in_message.body
        exchange.set_property("dynamic_route_used", target_route_id)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))


class ScatterGatherProcessor(BaseProcessor):
    """Fan-out на N маршрутов → сборка результатов.

    Отправляет копию Exchange на несколько DSL-маршрутов
    параллельно, собирает результаты в ``scatter_results``.
    """

    def __init__(
        self,
        route_ids: list[str],
        *,
        aggregation: str = "merge",
        timeout_seconds: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"scatter_gather({len(route_ids)})")
        self._route_ids = route_ids
        self._aggregation = aggregation
        self._timeout = timeout_seconds

    async def _call_route(
        self, route_id: str, body: Any, headers: dict, context: ExecutionContext
    ) -> tuple[str, Any, str | None]:
        from app.dsl.commands.registry import route_registry
        from app.dsl.engine.execution_engine import ExecutionEngine

        try:
            pipeline = route_registry.get(route_id)
            engine = ExecutionEngine()
            sub = await engine.execute(pipeline, body=body, headers=dict(headers), context=context)
            result = sub.out_message.body if sub.out_message else sub.in_message.body
            return route_id, result, sub.error
        except Exception as exc:
            return route_id, None, str(exc)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        tasks = [
            self._call_route(rid, exchange.in_message.body, exchange.in_message.headers, context)
            for rid in self._route_ids
        ]

        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            exchange.fail(f"Scatter-gather timeout ({self._timeout}s)")
            return

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for item in raw_results:
            if isinstance(item, Exception):
                errors["_exception"] = str(item)
            else:
                rid, result, error = item
                if error:
                    errors[rid] = error
                else:
                    results[rid] = result

        exchange.set_property("scatter_results", results)
        if errors:
            exchange.set_property("scatter_errors", errors)

        if self._aggregation == "merge" and results:
            merged: dict[str, Any] = {}
            for v in results.values():
                if isinstance(v, dict):
                    merged.update(v)
            exchange.set_out(body=merged, headers=dict(exchange.in_message.headers))


class ThrottlerProcessor(BaseProcessor):
    """Rate-limit per route: N сообщений в секунду.

    Использует token bucket для контроля пропускной
    способности. При превышении — задержка.
    """

    def __init__(
        self,
        rate: float,
        *,
        burst: int = 1,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"throttle({rate}/s)")
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = 0.0
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time

        async with self._lock:
            now = time.monotonic()
            if self._last_refill == 0.0:
                self._last_refill = now

            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


class DelayProcessor(BaseProcessor):
    """Задержка обработки на N миллисекунд или до timestamp."""

    def __init__(
        self,
        delay_ms: int | None = None,
        *,
        scheduled_time_fn: Callable[[Exchange[Any]], float] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"delay({delay_ms}ms)")
        self._delay_ms = delay_ms
        self._scheduled_fn = scheduled_time_fn

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import time

        if self._scheduled_fn is not None:
            target = self._scheduled_fn(exchange)
            now = time.time()
            if target > now:
                await asyncio.sleep(target - now)
        elif self._delay_ms is not None and self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000.0)


class SplitterProcessor(BaseProcessor):
    """Разбивает массив из body на отдельные Exchange.

    Каждый элемент обрабатывается sub-процессорами.
    Результаты собираются в ``split_results``.
    """

    def __init__(
        self,
        expression: str,
        processors: list[BaseProcessor],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"splitter:{expression[:20]}")
        self._expression = expression
        self._processors = processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import jmespath

        body = exchange.in_message.body
        items = jmespath.search(self._expression, body)
        if not isinstance(items, list):
            exchange.set_property("split_results", [])
            return

        results: list[Any] = []
        for item in items:
            sub_exchange = Exchange(
                in_message=Message(body=item, headers=dict(exchange.in_message.headers))
            )
            sub_exchange.status = ExchangeStatus.processing

            for proc in self._processors:
                if sub_exchange.status == ExchangeStatus.failed or sub_exchange.stopped:
                    break
                await proc.process(sub_exchange, context)

            result = (
                sub_exchange.out_message.body
                if sub_exchange.out_message
                else sub_exchange.in_message.body
            )
            results.append(result)

        exchange.set_property("split_results", results)
        exchange.set_out(body=results, headers=dict(exchange.in_message.headers))


class AggregatorProcessor(BaseProcessor):
    """Собирает N Exchange по correlation_id.

    Накапливает результаты в shared state (context.state),
    выдаёт агрегированный результат по достижении ``batch_size``
    или ``timeout``.
    """

    def __init__(
        self,
        correlation_key: Callable[[Exchange[Any]], str],
        *,
        batch_size: int = 10,
        timeout_seconds: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"aggregator(batch={batch_size})")
        self._corr_key = correlation_key
        self._batch_size = batch_size
        self._timeout = timeout_seconds
        self._buffers: dict[str, list[Any]] = {}
        self._lock = asyncio.Lock()

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = self._corr_key(exchange)

        async with self._lock:
            buf = self._buffers.setdefault(key, [])
            buf.append(exchange.in_message.body)

            if len(buf) >= self._batch_size:
                aggregated = list(buf)
                buf.clear()
                exchange.set_property("aggregated", True)
                exchange.set_out(body=aggregated, headers=dict(exchange.in_message.headers))
            else:
                exchange.set_property("aggregated", False)
                exchange.set_property("buffer_size", len(buf))
                exchange.stop()


class RecipientListProcessor(BaseProcessor):
    """Отправляет сообщение на динамический список маршрутов.

    Список маршрутов вычисляется из Exchange. Каждый получатель
    получает копию сообщения. Результаты собираются в property.
    """

    def __init__(
        self,
        recipients_expression: Callable[[Exchange[Any]], list[str]],
        *,
        parallel: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "recipient_list")
        self._expr = recipients_expression
        self._parallel = parallel

    async def _send_to(
        self, route_id: str, body: Any, headers: dict, context: ExecutionContext
    ) -> tuple[str, Any, str | None]:
        from app.dsl.commands.registry import route_registry
        from app.dsl.engine.execution_engine import ExecutionEngine

        try:
            pipeline = route_registry.get(route_id)
            engine = ExecutionEngine()
            sub = await engine.execute(pipeline, body=body, headers=dict(headers), context=context)
            result = sub.out_message.body if sub.out_message else sub.in_message.body
            return route_id, result, sub.error
        except Exception as exc:
            return route_id, None, str(exc)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        recipients = self._expr(exchange)
        if not recipients:
            return

        body = exchange.in_message.body
        headers = exchange.in_message.headers

        if self._parallel:
            tasks = [self._send_to(rid, body, headers, context) for rid in recipients]
            raw = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            raw = []
            for rid in recipients:
                raw.append(await self._send_to(rid, body, headers, context))

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for item in raw:
            if isinstance(item, Exception):
                errors["_exception"] = str(item)
            else:
                rid, result, error = item
                if error:
                    errors[rid] = error
                else:
                    results[rid] = result

        exchange.set_property("recipient_results", results)
        if errors:
            exchange.set_property("recipient_errors", errors)
