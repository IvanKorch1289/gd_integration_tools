"""S63 W2 — multicast.py part of routing decomp.

Classes: MulticastProcessor, MulticastRoutesProcessor.

MulticastProcessor + MulticastRoutesProcessor (1-to-many routing).
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor

_eip_logger = get_logger("dsl.eip")
_camel_logger = get_logger("dsl.camel")


class MulticastProcessor(BaseProcessor):
    """Camel Multicast EIP — send one message to N processor lists in parallel.

    Unlike ParallelProcessor (named branches), Multicast works with
    a flat list of processor groups and aggregates results.
    """

    def __init__(
        self,
        branches: list[list[BaseProcessor]],
        *,
        strategy: str = "all",
        stop_on_error: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"multicast({len(branches)})")
        self._branches = branches
        self._strategy = strategy
        self._stop_on_error = stop_on_error

    async def _run_branch(
        self,
        index: int,
        processors: list[BaseProcessor],
        body: Any,
        headers: dict[str, Any],
        context: ExecutionContext,
    ) -> tuple[int, Any, str | None]:
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
        return index, result, branch_exchange.error

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Execute branches in parallel and aggregate results."""
        body = exchange.in_message.body
        headers = exchange.in_message.headers

        tasks = [
            self._run_branch(i, procs, body, headers, context)
            for i, procs in enumerate(self._branches)
        ]

        results: list[Any] = [None] * len(self._branches)
        errors: dict[int, str] = {}

        if self._strategy == "first":
            registry = get_task_registry()
            done, pending = await asyncio.wait(
                [
                    registry.create_task(t, name=f"multicast-first:{idx}")
                    for idx, t in enumerate(tasks)
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                idx, result, error = task.result()
                if error:
                    errors[idx] = error
                else:
                    results[idx] = result
        else:
            for coro_result in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(coro_result, BaseException):
                    errors[-1] = str(coro_result)
                else:
                    idx, result, error = coro_result
                    results[idx] = result
                    if error:
                        errors[idx] = error
                        if self._stop_on_error:
                            break

        exchange.set_property("multicast_results", results)
        if errors:
            exchange.set_property("multicast_errors", errors)


class MulticastRoutesProcessor(BaseProcessor):
    """Fan-out на зарегистрированные DSL-маршруты по route_id.

    В отличие от ``MulticastProcessor`` (inline processor-groups),
    MulticastRoutesProcessor обращается к ``RouteRegistry`` и выполняет
    уже зарегистрированные маршруты как отдельные pipelines.

    Каждый маршрут получает копию текущего exchange body и headers.
    Результаты собираются в ``exchange.properties["multicast_route_results"]``.

    Args:
        route_ids: Список route_id для fan-out.
        strategy: ``all`` — выполнить все; ``first_success`` — вернуться после первого.
        on_error: ``fail`` — прерваться при ошибке; ``continue`` — продолжить.
        timeout: Таймаут ожидания результата каждого маршрута (секунды).
        name: Имя процессора в трассе.
    """

    def __init__(
        self,
        route_ids: list[str],
        *,
        strategy: str = "all",
        on_error: str = "continue",
        timeout: float = 30.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"multicast_routes({len(route_ids)})")
        if strategy not in {"all", "first_success"}:
            raise ValueError(
                f"MulticastRoutesProcessor: неверный strategy={strategy!r}."
            )
        if on_error not in {"fail", "continue"}:
            raise ValueError(
                f"MulticastRoutesProcessor: неверный on_error={on_error!r}."
            )
        self._route_ids = list(route_ids)
        self._strategy = strategy
        self._on_error = on_error
        self._timeout = timeout

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет fan-out на зарегистрированные маршруты."""
        from src.backend.dsl.commands.registry import route_registry
        from src.backend.dsl.engine.execution_engine import ExecutionEngine

        body = exchange.in_message.body
        headers = dict(exchange.in_message.headers)

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}

        engine = ExecutionEngine(route_registry=route_registry)

        async def _run_route(route_id: str) -> tuple[str, Any, str | None]:
            pipeline = route_registry.get_optional(route_id)
            if pipeline is None:
                return route_id, None, f"Маршрут {route_id!r} не зарегистрирован"
            branch_exchange = Exchange(
                in_message=Message(body=body, headers=dict(headers))
            )
            branch_exchange.status = ExchangeStatus.processing
            try:
                await asyncio.wait_for(
                    engine.execute(pipeline, exchange=branch_exchange, context=context),
                    timeout=self._timeout,
                )
            except TimeoutError:
                return route_id, None, f"Таймаут маршрута {route_id!r}"
            except Exception as exc:
                return route_id, None, str(exc)
            result_body = (
                branch_exchange.out_message.body
                if branch_exchange.out_message
                else branch_exchange.in_message.body
            )
            return route_id, result_body, branch_exchange.error

        registry = get_task_registry()
        tasks = [
            registry.create_task(_run_route(rid), name=f"multicast-route:{rid}")
            for rid in self._route_ids
        ]

        if self._strategy == "first_success":
            done, pending = await asyncio.wait(
                tasks, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            for task in done:
                rid, result, err = task.result()
                if err:
                    errors[rid] = err
                else:
                    results[rid] = result
                    break
        else:
            for completed in await asyncio.gather(*tasks, return_exceptions=True):
                if isinstance(completed, BaseException):
                    errors["__gather__"] = str(completed)
                    continue
                rid, result, err = completed
                if err:
                    errors[rid] = err
                    if self._on_error == "fail":
                        exchange.fail(f"Ошибка маршрута {rid!r}: {err}")
                        return
                else:
                    results[rid] = result

        exchange.set_property("multicast_route_results", results)
        if errors:
            exchange.set_property("multicast_route_errors", errors)
        _eip_logger.debug(
            "multicast_routes: %d/%d маршрутов успешно",
            len(results),
            len(self._route_ids),
        )

    def to_spec(self) -> dict:
        """YAML-spec для round-trip сериализации MulticastRoutesProcessor."""
        return {
            "multicast_routes": {
                "route_ids": list(self._route_ids),
                "strategy": self._strategy,
                "on_error": self._on_error,
                "timeout": self._timeout,
            }
        }
