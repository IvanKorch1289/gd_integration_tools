"""S63 W2 — scatter_gather.py part of routing decomp.

Classes: ScatterGatherProcessor.

ScatterGatherProcessor (fan-out + aggregate).
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_eip_logger = get_logger("dsl.eip")
_camel_logger = get_logger("dsl.camel")


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
        from src.backend.dsl.engine.processors.base import SubPipelineExecutor

        return await SubPipelineExecutor.execute_route_safe(
            route_id, body, headers, context
        )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполняет Scatter-Gather: параллельно рассылает сообщение во все маршруты и собирает результаты.

        ADR-0305: при наличии ``RequestContext.deadline_budget`` используется
        ``effective_timeout = min(self._timeout, deadline_remaining)`` —
        общий timeout всего fan-out ограничен deadline'ом запроса.
        Admission control: если budget истёк на входе — ``exchange.fail``
        без запуска tasks (no work, no wait, no leak).

        Args:
            exchange: Текущий обмен с сообщением-источником.
            context: Контекст выполнения процессора.

        """
        # ADR-0305: narrow scatter-gather timeout by remaining deadline budget.
        effective_timeout: float = self._timeout
        try:
            from src.backend.core.async_utils.deadline_budget import (
                DeadlineExpiredError,
            )
            from src.backend.core.request_context import RequestContext

            ctx = RequestContext.current()
            if ctx is not None and ctx.deadline_budget is not None:
                remaining = ctx.deadline_budget.remaining()
                if remaining <= 0.0:
                    # Deadline budget истёк — admission control: fan-out не стартует.
                    exchange.fail(
                        f"Scatter-gather skipped: deadline budget exhausted "
                        f"({len(self._route_ids)} routes, "
                        f"{ctx.deadline_budget.original_timeout}s total)"
                    )
                    return
                effective_timeout = min(self._timeout, remaining)
        except DeadlineExpiredError:
            raise
        except Exception:
            # Не ломаем scatter-gather при недоступности RequestContext.
            pass

        tasks = [
            self._call_route(
                rid, exchange.in_message.body, exchange.in_message.headers, context
            )
            for rid in self._route_ids
        ]

        try:
            raw_results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=effective_timeout,
            )
        except TimeoutError:
            exchange.fail(
                f"Scatter-gather timeout ({effective_timeout}s, "
                f"{len(self._route_ids)} routes)"
            )
            return

        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for item in raw_results:
            if isinstance(item, BaseException):
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
