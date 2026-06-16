"""Tests для ForkJoinProcessor (S93 W5) + DSL builder fork_join()."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip import ForkJoinProcessor


class _SetProperty(BaseProcessor):
    """Test processor: устанавливает value в property."""

    def __init__(self, key: str, value: Any) -> None:
        super().__init__(name=f"set_{key}")
        self._key = key
        self._value = value

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property(self._key, self._value)


class _SetBody(BaseProcessor):
    """Test processor: заменяет body."""

    def __init__(self, body: Any) -> None:
        super().__init__(name="set_body")
        self._body = body

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.in_message.body = self._body


class _FailProcessor(BaseProcessor):
    """Test processor: fails exchange."""

    def __init__(self, msg: str = "synthetic") -> None:
        super().__init__(name="fail_proc")
        self._msg = msg

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.fail(self._msg)


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


@pytest.mark.asyncio
async def test_fork_join_collect_aggregation(context: ExecutionContext) -> None:
    """collect (default): body = {branch_name: result} dict."""
    proc = ForkJoinProcessor(
        branches={"a": [_SetBody({"a-val": 1})], "b": [_SetBody({"b-val": 2})]},
        aggregation="collect",
    )
    exchange = Exchange(in_message=Message(body={"orig": 1}, headers={}))
    await proc.process(exchange, context)
    assert exchange.in_message.body == {"a": {"a-val": 1}, "b": {"b-val": 2}}
    assert exchange.get_property("fork_join_results") == {
        "a": {"a-val": 1},
        "b": {"b-val": 2},
    }


@pytest.mark.asyncio
async def test_fork_join_merge_dicts(context: ExecutionContext) -> None:
    """merge: B dict'ов → 1 dict."""
    proc = ForkJoinProcessor(
        branches={
            "user": [_SetBody({"user_id": 1, "name": "Alice"})],
            "order": [_SetBody({"order_id": 100, "total": 50})],
        },
        aggregation="merge",
    )
    exchange = Exchange(in_message=Message(body={}, headers={}))
    await proc.process(exchange, context)
    assert exchange.in_message.body == {
        "user_id": 1,
        "name": "Alice",
        "order_id": 100,
        "total": 50,
    }


@pytest.mark.asyncio
async def test_fork_join_merge_with_non_dict(context: ExecutionContext) -> None:
    """merge: non-dict values → branch_<i> keys."""
    proc = ForkJoinProcessor(
        branches={
            "dict_branch": [_SetBody({"a": 1})],
            "scalar_branch": [_SetBody("just-a-string")],
        },
        aggregation="merge",
    )
    exchange = Exchange(in_message=Message(body={}, headers={}))
    await proc.process(exchange, context)
    assert exchange.in_message.body == {"a": 1, "branch_1": "just-a-string"}


@pytest.mark.asyncio
async def test_fork_join_first_aggregation(context: ExecutionContext) -> None:
    """first: первый не-None результат становится body."""
    proc = ForkJoinProcessor(
        branches={
            "primary": [_SetBody({"source": "primary"})],
            "fallback": [_SetBody({"source": "fallback"})],
        },
        aggregation="first",
    )
    exchange = Exchange(in_message=Message(body=None, headers={}))
    await proc.process(exchange, context)
    # primary branch идёт первым (dict insertion order)
    assert exchange.in_message.body == {"source": "primary"}


@pytest.mark.asyncio
async def test_fork_join_first_skips_none(context: ExecutionContext) -> None:
    """first: пропускает None значения."""
    proc = ForkJoinProcessor(
        branches={"none_branch": [_SetBody(None)], "real_branch": [_SetBody({"v": 1})]},
        aggregation="first",
    )
    exchange = Exchange(in_message=Message(body="orig", headers={}))
    await proc.process(exchange, context)
    assert exchange.in_message.body == {"v": 1}


@pytest.mark.asyncio
async def test_fork_join_branch_failure_fails_exchange(
    context: ExecutionContext,
) -> None:
    """Любой branch fail → exchange fail (не silent drop)."""
    proc = ForkJoinProcessor(
        branches={"ok": [_SetProperty("k", "v")], "broken": [_FailProcessor("kaboom")]}
    )
    exchange = Exchange(in_message=Message(body={}, headers={}))
    await proc.process(exchange, context)
    assert exchange.status == ExchangeStatus.failed
    assert "kaboom" in (exchange.error or "")


@pytest.mark.asyncio
async def test_fork_join_empty_branches_raises() -> None:
    """Пустой branches → ValueError."""
    with pytest.raises(ValueError, match="branches cannot be empty"):
        ForkJoinProcessor(branches={})


def test_fork_join_invalid_aggregation_raises() -> None:
    """Неизвестная aggregation → ValueError."""
    with pytest.raises(ValueError, match="aggregation must be one of"):
        ForkJoinProcessor(branches={"a": [_SetProperty("k", 1)]}, aggregation="bogus")


def test_fork_join_dsl_builder_method_exists() -> None:
    """DSL RouteBuilder имеет метод fork_join (S93 W5)."""
    from src.backend.dsl.builder import RouteBuilder

    assert hasattr(RouteBuilder, "fork_join"), "RouteBuilder.fork_join missing"
    # Method signature check
    import inspect

    sig = inspect.signature(RouteBuilder.fork_join)
    params = list(sig.parameters.keys())
    assert "branches" in params
    assert "aggregation" in params
    assert "timeout_seconds" in params
