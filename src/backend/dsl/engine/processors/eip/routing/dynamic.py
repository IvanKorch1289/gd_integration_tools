"""S63 W2 — dynamic.py part of routing decomp.

Classes: DynamicRouterProcessor.

DynamicRouterProcessor (runtime-decided routing).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_eip_logger = get_logger("dsl.eip")
_camel_logger = get_logger("dsl.camel")


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
        """Метод process (см. signature).

        ADR-0305: ``DynamicRouterProcessor`` не имеет собственного timeout.
        Deadline integration: admission control на входе через
        ``budget.is_expired()`` — expired → ``exchange.fail`` без вычисления target.
        """
        # ADR-0305: admission control для DynamicRouter (нет timeout для narrow).
        try:
            from src.backend.core.async_utils.deadline_budget import (  # noqa: F401 — re-export
                DeadlineExpiredError,
            )
            from src.backend.core.request_context import RequestContext

            ctx = RequestContext.current()
            if ctx is not None and ctx.deadline_budget is not None:
                if ctx.deadline_budget.is_expired():
                    exchange.fail(
                        f"DynamicRouter skipped: deadline budget exhausted "
                        f"({ctx.deadline_budget.original_timeout}s total)"
                    )
                    return
        except DeadlineExpiredError:
            raise
        except Exception:
            # Не ломаем dynamic-router при недоступности RequestContext.
            pass

        from src.backend.dsl.commands.registry import route_registry
        from src.backend.dsl.engine.processors.base import SubPipelineExecutor

        target_route_id = self._expr(exchange)
        if not route_registry.is_registered(target_route_id):
            exchange.fail(f"Dynamic route '{target_route_id}' not found")
            return

        result, error = await SubPipelineExecutor.execute_route(
            target_route_id,
            exchange.in_message.body,
            dict(exchange.in_message.headers),
            context,
        )
        if error:
            exchange.fail(f"Dynamic route '{target_route_id}' failed: {error}")
            return

        exchange.set_property("dynamic_route_used", target_route_id)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
