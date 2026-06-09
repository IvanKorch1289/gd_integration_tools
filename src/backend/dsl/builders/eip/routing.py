"""Routing EIP-методы: dynamic_route / scatter_gather / routing_slip /
content_based_router / sampling / load_balance / multicast_routes.

Sprint 60 W4 — split из eip.py (1354 LOC).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from src.backend.dsl.builders.eip._base import EIPMixinBase
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors import (
    DynamicRouterProcessor,
    LoadBalancerProcessor,
    ScatterGatherProcessor,
)

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("RoutingEIPsMixin",)


class RoutingEIPsMixin(EIPMixinBase):
    """EIP routing patterns: dynamic / scatter-gather / routing slip / CBR / sampling / load balance / multicast."""

    def translate(self, from_format: str, to_format: str) -> "RouteBuilder":
        """DEPRECATED: используйте .convert(). translate() — alias для обратной совместимости."""
        return self.convert(from_format=from_format, to_format=to_format)  # type: ignore[attr-defined]

    def dynamic_route(
        self, route_expression: Callable[[Exchange[Any]], str]
    ) -> "RouteBuilder":
        """Dynamic Router: runtime-вычисление route_id."""
        return cast(
            "RouteBuilder",
            self._add(DynamicRouterProcessor(route_expression=route_expression)),
        )  # type: ignore[attr-defined]

    def scatter_gather(
        self,
        route_ids: list[str],
        *,
        aggregation: str = "merge",
        timeout_seconds: float = 30.0,
    ) -> "RouteBuilder":
        """Scatter-Gather: fan-out на N маршрутов + сборка результатов."""
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                ScatterGatherProcessor(
                    route_ids=route_ids,
                    aggregation=aggregation,
                    timeout_seconds=timeout_seconds,
                )
            ),
        )

    def routing_slip(
        self,
        steps: Callable[[Exchange[Any]], Any] | list[str],
        *,
        header: str | None = None,
        strict: bool = True,
        max_steps: int = 50,
    ) -> "RouteBuilder":
        """Routing Slip EIP: динамическая цепочка processors per-message.

        Apache Camel Routing Slip: https://camel.apache.org/components/latest/eips/routingSlip.html

        Каждое сообщение определяет свой ordered список steps, через которые
        message проходит последовательно. Отличие от Pipeline: steps
        определяются runtime'ом (per-message) — не статически.

        Args:
            steps: list имен processors ИЛИ callable, возвращающий list
                (для динамического выбора на основе exchange).
            header: имя header в exchange, который содержит list имен
                steps. Удобно когда список приходит извне.
            strict: если True (default) — отсутствующий step → KeyError.
                Если False — warning + skip.
            max_steps: защита от бесконечной цепочки (default 50).

        Пример::

            # Static steps
            .routing_slip(["audit", "transform", "send"])

            # Dynamic (per-message)
            .routing_slip(
                steps=lambda ex: ex.in_message.headers.get("flow"),
                strict=True,
            )

            # From header
            .routing_slip(steps=[], header="processing_pipeline")
        """
        from src.backend.dsl.engine.processors.eip.routing_slip import (
            ProcessorRegistry,
            RoutingSlipProcessor,
        )
        from src.backend.dsl.registry.processor import get_processor_registry

        # Resolve steps: list → constant, callable → wrap
        if isinstance(steps, list):
            _steps_list: list[str] = list(steps)  # capture by value

            def _const_resolver(e: Exchange[Any]) -> Any:
                return _steps_list  # type: ignore[misc]

            steps_resolver: Callable[[Exchange[Any]], Any] = _const_resolver
        else:
            steps_resolver = steps

        # If header specified, override resolver
        if header is not None:
            _h: str = header

            def _from_header(e: Exchange[Any]) -> Any:
                val = e.in_message.headers.get(_h)
                if val is None:
                    return []
                if isinstance(val, str):
                    return [s.strip() for s in val.split(",")]
                return list(val)

            steps_resolver = _from_header

        registry: ProcessorRegistry = get_processor_registry()

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                RoutingSlipProcessor(
                    steps_resolver=steps_resolver,
                    registry=registry,
                    strict=strict,
                    max_steps=max_steps,
                )
            ),
        )

    def content_based_router(
        self,
        routes: list[tuple[Callable[[Exchange[Any]], bool], str]],
        *,
        default_endpoint: str | None = None,
    ) -> "RouteBuilder":
        """Content-Based Router EIP: route по predicate.

        Apache Camel: https://camel.apache.org/components/latest/eips/contentBasedRouter.html

        First matching predicate wins. Если ни один не match и default_endpoint
        задан → туда; иначе message dropped.

        Пример::

            .content_based_router([
                (lambda ex: ex.in_message.body.get("priority") == "high", "high_pri"),
                (lambda ex: ex.in_message.body.get("country") == "ru", "ru_route"),
            ], default_endpoint="default")
        """
        from src.backend.dsl.engine.processors.eip.filter_router_sampling import (
            ContentBasedRouter as _CBR,
        )

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                _CBR(routes=routes, default_endpoint=default_endpoint)
            ),
        )

    def sampling(
        self,
        *,
        rate: int | None = None,
        fraction: float | None = None,
        time_window_ms: int | None = None,
        max_in_window: int | None = None,
        seed: int | None = None,
    ) -> "RouteBuilder":
        """Sampling EIP: probabilistic subset of messages.

        Apache Camel: https://camel.apache.org/components/latest/eips/sampling.html

        Пример::

            # 10% sampling
            .sampling(fraction=0.1)

            # Каждый 100-й
            .sampling(rate=100)

            # 5 per second
            .sampling(time_window_ms=1000, max_in_window=5)
        """
        from src.backend.dsl.engine.processors.eip.filter_router_sampling import (
            SamplingProcessor as _SP,
        )

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                _SP(
                    rate=rate,
                    fraction=fraction,
                    time_window_ms=time_window_ms,
                    max_in_window=max_in_window,
                    seed=seed,
                )
            ),
        )

    def load_balance(
        self,
        targets: list[str],
        *,
        strategy: str = "round_robin",
        weights: list[float] | None = None,
        sticky_header: str | None = None,
    ) -> "RouteBuilder":
        """Load Balancer: round_robin/random/weighted/sticky распределение."""
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                LoadBalancerProcessor(
                    targets=targets,
                    strategy=strategy,
                    weights=weights,
                    sticky_header=sticky_header,
                )
            ),
        )

    def multicast_routes(
        self,
        route_ids: list[str],
        *,
        strategy: str = "all",
        on_error: str = "continue",
        timeout: float = 30.0,
    ) -> "RouteBuilder":
        """Fan-out на зарегистрированные DSL-маршруты по route_id.

        Args:
            route_ids: Список route_id из RouteRegistry.
            strategy: ``all`` — выполнить все; ``first_success`` — остановить после первого.
            on_error: ``fail`` | ``continue`` — поведение при ошибке.
            timeout: Таймаут каждого маршрута в секундах.
        """
        from src.backend.dsl.engine.processors.eip.routing import (
            MulticastRoutesProcessor,
        )

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                MulticastRoutesProcessor(
                    route_ids=route_ids,
                    strategy=strategy,
                    on_error=on_error,
                    timeout=timeout,
                )
            ),
        )
