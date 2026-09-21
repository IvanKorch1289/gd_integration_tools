"""Тесты MiddlewareMixin / per-route middleware DSL."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.middleware import (
    ErrorNormalizerMiddleware,
    MetricsMiddleware,
    MiddlewareChain,
    TimeoutMiddleware,
)
from src.backend.dsl.engine.processors import CallableProcessor


class _DummyProcessor:
    name = "dummy"

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        await asyncio.sleep(0)
        exchange.set_property("processed", True)


def test_middleware_accepts_string_timeout() -> None:
    """middleware('timeout', seconds=10) добавляет TimeoutMiddleware."""
    pipeline = (
        RouteBuilder.from_("route.1", source="internal:test")
        .middleware("timeout", seconds=10.0)
        .build(validate_actions=False)
    )

    assert len(pipeline.middlewares) == 1
    assert isinstance(pipeline.middlewares[0], TimeoutMiddleware)
    assert pipeline.middlewares[0]._default_timeout == 10.0


def test_middleware_accepts_string_error_normalizer() -> None:
    """middleware('error_normalizer') добавляет ErrorNormalizerMiddleware."""
    pipeline = (
        RouteBuilder.from_("route.2", source="internal:test")
        .middleware("error_normalizer")
        .build(validate_actions=False)
    )

    assert len(pipeline.middlewares) == 1
    assert isinstance(pipeline.middlewares[0], ErrorNormalizerMiddleware)


def test_middleware_accepts_string_metrics() -> None:
    """middleware('metrics') добавляет MetricsMiddleware."""
    pipeline = (
        RouteBuilder.from_("route.3", source="internal:test")
        .middleware("metrics")
        .build(validate_actions=False)
    )

    assert len(pipeline.middlewares) == 1
    assert isinstance(pipeline.middlewares[0], MetricsMiddleware)


def test_middleware_accepts_instance() -> None:
    """middleware(instance) принимает готовый ProcessorMiddleware."""
    instance = TimeoutMiddleware(default_timeout=5.0)
    pipeline = (
        RouteBuilder.from_("route.4", source="internal:test")
        .middleware(instance)
        .build(validate_actions=False)
    )

    assert pipeline.middlewares == [instance]


def test_middleware_accepts_dict() -> None:
    """middleware({'type': 'timeout', 'seconds': 7}) парсит spec."""
    pipeline = (
        RouteBuilder.from_("route.5", source="internal:test")
        .middleware({"type": "timeout", "seconds": 7.0})
        .build(validate_actions=False)
    )

    assert len(pipeline.middlewares) == 1
    assert isinstance(pipeline.middlewares[0], TimeoutMiddleware)
    assert pipeline.middlewares[0]._default_timeout == 7.0


def test_middleware_unknown_name_raises() -> None:
    """Неизвестное имя middleware бросает ValueError."""
    builder = RouteBuilder.from_("route.6", source="internal:test")
    with pytest.raises(ValueError):
        builder.middleware("unknown")


def test_middleware_bad_type_raises() -> None:
    """middleware(int) бросает TypeError."""
    builder = RouteBuilder.from_("route.7", source="internal:test")
    with pytest.raises(TypeError):
        builder.middleware(123)  # type: ignore[arg-type]


def test_execution_engine_builds_chain_with_route_override() -> None:
    """ExecutionEngine заменяет default TimeoutMiddleware route-specific."""
    default_chain = MiddlewareChain(
        [TimeoutMiddleware(default_timeout=30.0), ErrorNormalizerMiddleware()]
    )
    engine = ExecutionEngine(middleware=default_chain, validate_before_execute=False)

    pipeline = (
        RouteBuilder.from_("route.8", source="internal:test")
        .middleware("timeout", seconds=2.5)
        .middleware("metrics")
        .build(validate_actions=False)
    )

    chain = engine._build_chain(pipeline)
    mws = list(chain.iter_middlewares())
    assert len(mws) == 3
    assert isinstance(mws[0], TimeoutMiddleware)
    assert mws[0]._default_timeout == 2.5
    assert isinstance(mws[1], ErrorNormalizerMiddleware)
    assert isinstance(mws[2], MetricsMiddleware)


@pytest.mark.asyncio
async def test_execution_engine_uses_route_timeout() -> None:
    """Route-specific timeout применяется к процессору."""
    default_chain = MiddlewareChain(
        [TimeoutMiddleware(default_timeout=30.0), ErrorNormalizerMiddleware()]
    )
    engine = ExecutionEngine(middleware=default_chain, validate_before_execute=False)

    async def _slow_process(exchange: Exchange[Any], context: Any) -> None:
        await asyncio.sleep(1.0)

    pipeline = (
        RouteBuilder.from_("route.9", source="internal:test")
        .process(CallableProcessor(func=_slow_process, name="slow"))
        .middleware("timeout", seconds=0.05)
        .build(validate_actions=False)
    )

    result = await engine.execute(pipeline, body={})
    assert result.status == ExchangeStatus.failed


def test_build_chain_without_route_middleware_uses_defaults() -> None:
    """Pipeline без middlewares получает только default chain."""
    default_chain = MiddlewareChain([TimeoutMiddleware(default_timeout=30.0)])
    engine = ExecutionEngine(middleware=default_chain, validate_before_execute=False)

    pipeline = RouteBuilder.from_("route.10", source="internal:test").build(
        validate_actions=False
    )

    chain = engine._build_chain(pipeline)
    mws = list(chain.iter_middlewares())
    assert len(mws) == 1
    assert isinstance(mws[0], TimeoutMiddleware)
    assert mws[0]._default_timeout == 30.0
