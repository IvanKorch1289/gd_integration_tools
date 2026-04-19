import asyncio
import logging
import time
from typing import Any, Callable

import orjson

from app.dsl.engine.context import ExecutionContext
from app.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from app.dsl.engine.processors.base import BaseProcessor

_eip_logger = logging.getLogger("dsl.eip")
_camel_logger = logging.getLogger("dsl.camel")

__all__ = ('DynamicRouterProcessor', 'ScatterGatherProcessor', 'RecipientListProcessor', 'LoadBalancerProcessor', 'MulticastProcessor')


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
        from app.dsl.engine.processors.base import SubPipelineExecutor

        target_route_id = self._expr(exchange)
        if not route_registry.is_registered(target_route_id):
            exchange.fail(f"Dynamic route '{target_route_id}' not found")
            return

        result, error = await SubPipelineExecutor.execute_route(
            target_route_id, exchange.in_message.body,
            dict(exchange.in_message.headers), context,
        )
        if error:
            exchange.fail(f"Dynamic route '{target_route_id}' failed: {error}")
            return

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
        from app.dsl.engine.processors.base import SubPipelineExecutor

        return await SubPipelineExecutor.execute_route_safe(
            route_id, body, headers, context,
        )

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
        from app.dsl.engine.processors.base import SubPipelineExecutor

        return await SubPipelineExecutor.execute_route_safe(
            route_id, body, headers, context,
        )

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


# ---------------------------------------------------------------------------
#  Apache Camel EIP v2 — LoadBalancer, CircuitBreaker, ClaimCheck,
#  Normalizer, Resequencer, Multicast
# ---------------------------------------------------------------------------



class LoadBalancerProcessor(BaseProcessor):
    """Camel Load Balancer EIP — distributes exchanges across multiple routes.

    Strategies: round_robin, random, weighted, sticky (header-based).
    """

    def __init__(
        self,
        targets: list[str],
        *,
        strategy: str = "round_robin",
        weights: list[float] | None = None,
        sticky_header: str | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"load_balancer({strategy})")
        self._targets = targets
        self._strategy = strategy
        self._weights = weights
        self._sticky_header = sticky_header
        self._rr_index = 0
        self._lock = asyncio.Lock()

    async def _select_target(self, exchange: Exchange[Any]) -> str:
        if self._strategy == "round_robin":
            async with self._lock:
                target = self._targets[self._rr_index % len(self._targets)]
                self._rr_index += 1
            return target

        if self._strategy == "random":
            import random as _random
            return _random.choice(self._targets)

        if self._strategy == "weighted" and self._weights:
            import random as _random
            return _random.choices(self._targets, weights=self._weights, k=1)[0]

        if self._strategy == "sticky" and self._sticky_header:
            key = exchange.in_message.headers.get(self._sticky_header, "")
            idx = hash(key) % len(self._targets)
            return self._targets[idx]

        return self._targets[0]

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from app.dsl.engine.processors.base import SubPipelineExecutor

        target = await self._select_target(exchange)
        exchange.set_property("lb_target", target)

        result, error = await SubPipelineExecutor.execute_route(
            target, exchange.in_message.body,
            dict(exchange.in_message.headers), context,
        )
        if error:
            exchange.fail(f"Load balancer target '{target}' failed: {error}")
            return
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))



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
        return index, result, branch_exchange.error

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        headers = exchange.in_message.headers

        tasks = [
            self._run_branch(i, procs, body, headers, context)
            for i, procs in enumerate(self._branches)
        ]

        results: list[Any] = [None] * len(self._branches)
        errors: dict[int, str] = {}

        if self._strategy == "first":
            done, pending = await asyncio.wait(
                [asyncio.create_task(t) for t in tasks],
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
                if isinstance(coro_result, Exception):
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


# ---------------------------------------------------------------------------
#  Apache Camel EIP v3 — Loop, OnCompletion, Sort, Timeout
# ---------------------------------------------------------------------------


