import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from app.dsl.engine.processors.base import BaseProcessor

_cf_logger = logging.getLogger("dsl.control_flow")

__all__ = (
    "ChoiceProcessor",
    "TryCatchProcessor",
    "RetryProcessor",
    "PipelineRefProcessor",
    "ParallelProcessor",
    "SagaStep",
    "SagaProcessor",
)


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
