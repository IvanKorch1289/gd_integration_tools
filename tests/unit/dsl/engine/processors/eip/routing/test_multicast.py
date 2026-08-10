"""Unit-тесты MulticastRoutesProcessor (cycle-1/B-04 regression).

Цель: зафиксировать, что ``MulticastRoutesProcessor.process()`` использует
**реальный** ``ExecutionEngine`` (а не мок конструктора). До фикса
``multicast.py:172`` передавал ``route_registry=...`` — kwarg, которого нет
в ``ExecutionEngine.__init__``. Тесты собирают настоящий engine, реальный
``Pipeline`` через ``RouteRegistry``, что воспроизводит production-runtime.

Покрытие:
    * ``strategy=all`` + ``on_error=continue``: успешный fan-out собирает
      результаты всех маршрутов.
    * ``strategy=all`` + ``on_error=fail``: ошибка в маршруте → exchange.fail().
    * Незарегистрированный route_id → запись в ``multicast_route_errors``.
    * Конструктор ExecutionEngine без ``route_registry`` kwarg (no-TypeError guard).

cycle-1/B-04
"""


from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch

import pytest

from src.backend.dsl.commands.registry import RouteRegistry
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.routing.multicast import (
    MulticastRoutesProcessor,
)


class _SetBodyProcessor(BaseProcessor):
    """Минимальный процессор для заполнения out_message.body = marker."""

    def __init__(self, marker: str, name: str | None = None) -> None:
        super().__init__(name=name or f"set_body({marker})")
        self._marker = marker

    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext,
    ) -> None:
        exchange.out_message = Message(body={"marker": self._marker})


def _exchange(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body or {"input": 1}))


def _ctx() -> ExecutionContext:
    return ExecutionContext(route_id="multicast-b04-test")


def _build_registry_with_routes(route_specs: dict[str, list[BaseProcessor]]) -> RouteRegistry:
    """Строит реальный RouteRegistry с реальными Pipeline для каждого route_id.

    Args:
        route_specs: ``{route_id: [processor, ...]}``.

    Returns:
        Готовый RouteRegistry с зарегистрированными pipelines.

    """
    registry = RouteRegistry()
    for rid, procs in route_specs.items():
        pipeline = Pipeline(route_id=rid, processors=list(procs))
        registry.register(pipeline)
    return registry


def test_execution_engine_init_signature_has_no_route_registry_kwarg() -> None:
    """Regression: ``ExecutionEngine.__init__`` НЕ принимает ``route_registry``.

    До фикса cycle-1/B-04 ``multicast.py:172`` вызывал
    ``ExecutionEngine(route_registry=...)`` — kwarg отсутствовал, на
    Python 3.14 падало с TypeError в production. Тест фиксирует канон.
    """
    sig = inspect.signature(ExecutionEngine.__init__)
    assert "route_registry" not in sig.parameters, (
        "ExecutionEngine.__init__ не должен принимать route_registry — "
        "это module-level lookup в MulticastRoutesProcessor.process()"
    )


def test_execution_engine_constructs_without_args() -> None:
    """Regression: ``ExecutionEngine()`` собирается без TypeError.

    До фикса multicast.py передавал ``route_registry=...`` → TypeError.
    После фикса ``ExecutionEngine()`` использует default MiddlewareChain
    + ProcessorPool.
    """
    engine = ExecutionEngine()
    assert engine is not None
    assert hasattr(engine, "execute")


@pytest.mark.asyncio
async def test_multicast_routes_all_with_real_engine() -> None:
    """strategy=all + on_error=continue: реальный engine fan-out, все результаты собраны."""
    registry = _build_registry_with_routes(
        {
            "alpha": [_SetBodyProcessor("A")],
            "beta": [_SetBodyProcessor("B")],
        },
    )

    proc = MulticastRoutesProcessor(
        route_ids=["alpha", "beta"], strategy="all", on_error="continue",
    )
    ex = _exchange()

    with patch("src.backend.dsl.commands.registry.route_registry", registry):
        await proc.process(ex, _ctx())

    results = ex.properties.get("multicast_route_results", {})
    assert results == {
        "alpha": {"marker": "A"},
        "beta": {"marker": "B"},
    }
    assert "multicast_route_errors" not in ex.properties
    assert ex.status != ExchangeStatus.failed


@pytest.mark.asyncio
async def test_multicast_routes_unregistered_route_with_real_engine() -> None:
    """Незарегистрированный route → запись в multicast_route_errors, exchange OK."""
    registry = _build_registry_with_routes({"known": [_SetBodyProcessor("K")]})

    proc = MulticastRoutesProcessor(
        route_ids=["known", "missing"], strategy="all", on_error="continue",
    )
    ex = _exchange()

    with patch("src.backend.dsl.commands.registry.route_registry", registry):
        await proc.process(ex, _ctx())

    results = ex.properties.get("multicast_route_results", {})
    errors = ex.properties.get("multicast_route_errors", {})

    assert results == {"known": {"marker": "K"}}
    assert "missing" in errors
    assert "не зарегистрирован" in errors["missing"]


@pytest.mark.asyncio
async def test_multicast_routes_on_error_fail_with_real_engine() -> None:
    """on_error=fail: ошибка маршрута → exchange.fail + ранний return."""
    class _Boom(BaseProcessor):
        async def process(
            self, exchange: Exchange[Any], context: ExecutionContext,
        ) -> None:
            raise RuntimeError("real-engine-boom")

    registry = _build_registry_with_routes({"bad": [_Boom()]})

    proc = MulticastRoutesProcessor(
        route_ids=["bad"], strategy="all", on_error="fail",
    )
    ex = _exchange()

    with patch("src.backend.dsl.commands.registry.route_registry", registry):
        await proc.process(ex, _ctx())

    assert ex.status == ExchangeStatus.failed
    assert "real-engine-boom" in (ex.error or "")
    assert "bad" in (ex.error or "")


@pytest.mark.asyncio
async def test_multicast_routes_first_success_with_real_engine() -> None:
    """strategy=first_success: первый завершённый результат сохранён, остальные отменены.

    Чтобы asyncio.wait(FIRST_COMPLETED) детерминированно выбрал ``slow``,
    маршрут ``slow`` делает ``asyncio.sleep`` — ``fast`` отменяется pending.
    """
    import asyncio

    class _SlowProcessor(BaseProcessor):
        def __init__(self, marker: str) -> None:
            super().__init__(name=f"slow({marker})")
            self._marker = marker

        async def process(
            self, exchange: Exchange[Any], context: ExecutionContext,
        ) -> None:
            await asyncio.sleep(0.05)
            exchange.out_message = Message(body={"marker": self._marker})

    class _FastProcessor(BaseProcessor):
        def __init__(self, marker: str) -> None:
            super().__init__(name=f"fast({marker})")
            self._marker = marker

        async def process(
            self, exchange: Exchange[Any], context: ExecutionContext,
        ) -> None:
            # fast отменяется pending — out_message не должен записаться.
            await asyncio.sleep(5.0)
            exchange.out_message = Message(body={"marker": self._marker})

    registry = _build_registry_with_routes(
        {
            "fast": [_FastProcessor("FAST")],
            "slow": [_SlowProcessor("SLOW")],
        },
    )

    proc = MulticastRoutesProcessor(
        route_ids=["fast", "slow"], strategy="first_success",
    )
    ex = _exchange()

    with patch("src.backend.dsl.commands.registry.route_registry", registry):
        await proc.process(ex, _ctx())

    results = ex.properties.get("multicast_route_results", {})
    # В стратегии first_success ``slow`` завершается раньше — он и попадает в results.
    assert len(results) == 1
    assert "slow" in results
    assert "fast" not in results
