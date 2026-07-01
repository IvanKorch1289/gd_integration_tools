"""S55 W2 — parallel.py part of control_flow decomp.

Classes: PipelineRefProcessor, ParallelProcessor.
Funcs: .
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow.saga import _serialize_sub

_cf_logger = get_logger("dsl.control_flow")


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
        from src.backend.dsl.engine.processors.base import SubPipelineExecutor

        result, error = await SubPipelineExecutor.execute_route(
            self._route_id,
            exchange.in_message.body,
            dict(exchange.in_message.headers),
            context,
        )
        if error:
            exchange.fail(f"Sub-pipeline '{self._route_id}' failed: {error}")
            return

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
        branch_exchange = Exchange(in_message=Message(body=body, headers=dict(headers)))
        branch_exchange.status = ExchangeStatus.processing

        for proc in processors:
            if (
                branch_exchange.status == ExchangeStatus.failed
                or branch_exchange.stopped
            ):
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
        """Параллельно выполняет несколько веток processors с разными стратегиями.

        Стратегия ``all`` (default): ``asyncio.gather`` всех веток, ожидание всех.
        Стратегия ``first``: ``asyncio.FIRST_COMPLETED``, отмена остальных веток.

        Каждая ветка получает копию exchange. Результаты — в свойстве
        ``parallel_results``, ошибки — в ``parallel_errors``.

        Args:
            exchange: Текущий exchange; body+headers копируются в каждую ветку.
            context: Контекст выполнения маршрута.
        """
        body = exchange.in_message.body
        headers = exchange.in_message.headers

        tasks = [
            self._run_branch(name, procs, body, headers, context)
            for name, procs in self._branches.items()
        ]

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}

        if self._strategy == "first":
            registry = get_task_registry()
            done, pending = await asyncio.wait(
                [
                    registry.create_task(t, name=f"branch:first:{idx}")
                    for idx, t in enumerate(tasks)
                ],
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
                if isinstance(coro_result, BaseException):
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

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует параллельные ветки в YAML-spec.

        Returns:
            ``{"parallel": {branches: {name: [...]}, strategy}}`` или ``None``.
        """
        branches_spec: dict[str, list[dict[str, Any]]] = {}
        for name, procs in self._branches.items():
            sub = _serialize_sub(procs)
            if sub is None:
                return None
            branches_spec[name] = sub
        return {"parallel": {"branches": branches_spec, "strategy": self._strategy}}
