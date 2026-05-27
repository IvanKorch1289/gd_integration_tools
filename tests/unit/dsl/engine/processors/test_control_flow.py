"""Unit-тесты control-flow процессоров: TryCatchProcessor, ParallelProcessor, ChoiceProcessor.

Покрывают поведение (не сериализацию round-trip).

Паттерн: async tests, _ex fixture, asyncio tests — аналогично test_batch_processor.py.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from typing import Any, Callable
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import CallableProcessor
from src.backend.dsl.engine.processors.control_flow import (
    ChoiceBranch,
    ChoiceProcessor,
    ParallelProcessor,
    TryCatchProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


def _proc(fn: Callable[..., Any]) -> CallableProcessor:
    """Оборачивает async fn в CallableProcessor."""
    return CallableProcessor(fn)


# =============================================================================
# TryCatchProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_try_catch_success() -> None:
    """Try выполняется, catch не вызывается."""
    call_log: list[str] = []

    async def try_step(ex: Exchange[Any], ctx: Any) -> None:
        ex.out_message = Message(body={"status": "ok"})
        call_log.append("try")

    async def catch_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("catch")

    proc = TryCatchProcessor(
        try_processors=[_proc(try_step)],
        catch_processors=[_proc(catch_step)],
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == ["try"]
    assert e.out_message.body == {"status": "ok"}


@pytest.mark.asyncio
async def test_try_catch_exception_caught() -> None:
    """Exception в try → catch выполняется, error в properties."""
    call_log: list[str] = []

    async def failing_try(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("try")
        raise RuntimeError("boom")

    async def catch_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("catch")

    proc = TryCatchProcessor(
        try_processors=[_proc(failing_try)],
        catch_processors=[_proc(catch_step)],
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == ["try", "catch"]
    assert e.properties.get("caught_error") == "boom"


@pytest.mark.asyncio
async def test_try_catch_finally_always_runs() -> None:
    """Finally выполняется и при успехе, и при ошибке."""
    call_log: list[str] = []

    async def try_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("try")

    async def catch_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("catch")

    async def finally_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("finally")

    proc = TryCatchProcessor(
        try_processors=[_proc(try_step)],
        catch_processors=[_proc(catch_step)],
        finally_processors=[_proc(finally_step)],
    )
    ctx = AsyncMock()

    # Успешный try
    e_ok = _ex(body={"ok": True})
    await proc.process(e_ok, ctx)
    assert call_log == ["try", "finally"]

    # Exception в try
    async def failing_try(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("try_ex")
        raise ValueError("fail")

    proc2 = TryCatchProcessor(
        try_processors=[_proc(failing_try)],
        catch_processors=[_proc(catch_step)],
        finally_processors=[_proc(finally_step)],
    )
    e_fail = _ex(body={"fail": True})
    await proc2.process(e_fail, ctx)
    assert call_log == ["try", "finally", "try_ex", "catch", "finally"]


@pytest.mark.asyncio
async def test_try_catch_exchange_status_recovered() -> None:
    """После catch (по exception) status = processing, error cleared, caught_error set."""
    async def failing_try(ex: Exchange[Any], ctx: Any) -> None:
        raise RuntimeError("boom")

    proc = TryCatchProcessor(
        try_processors=[_proc(failing_try)],
        catch_processors=[],
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    # Status восстанавливается в processing (catch processors пустые, finally нет)
    assert e.status == ExchangeStatus.pending
    assert e.error is None
    # caught_error выставляется от RuntimeError
    assert e.properties.get("caught_error") == "boom"


@pytest.mark.asyncio
async def test_try_catch_with_failed_exchange_not_exception() -> None:
    """Exchange.status=failed без exception → catch вызывается."""
    call_log: list[str] = []

    async def fail_exchange(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("try")
        ex.fail("pre-fail")

    async def catch_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("catch")

    proc = TryCatchProcessor(
        try_processors=[_proc(fail_exchange)],
        catch_processors=[_proc(catch_step)],
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == ["try", "catch"]
    assert e.properties.get("caught_error") == "pre-fail"


# =============================================================================
# ParallelProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_parallel_all_strategy_collects_results() -> None:
    """2 ветки, strategy='all', results в parallel_results."""
    async def branch_a(ex: Exchange[Any], ctx: Any) -> None:
        ex.out_message = Message(body={"branch": "a", "value": 1})

    async def branch_b(ex: Exchange[Any], ctx: Any) -> None:
        ex.out_message = Message(body={"branch": "b", "value": 2})

    proc = ParallelProcessor(
        branches={
            "a": [_proc(branch_a)],
            "b": [_proc(branch_b)],
        },
        strategy="all",
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "x"})

    await proc.process(e, ctx)

    results = e.properties.get("parallel_results", {})
    assert results.get("a") == {"branch": "a", "value": 1}
    assert results.get("b") == {"branch": "b", "value": 2}


@pytest.mark.asyncio
async def test_parallel_first_strategy_returns_first() -> None:
    """strategy='first' возвращает первый успешный."""
    call_log: list[str] = []

    async def slow_branch(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("slow_start")
        await asyncio.sleep(0.05)
        call_log.append("slow_done")
        ex.out_message = Message(body={"branch": "slow"})

    async def fast_branch(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("fast")
        ex.out_message = Message(body={"branch": "fast"})

    proc = ParallelProcessor(
        branches={
            "slow": [_proc(slow_branch)],
            "fast": [_proc(fast_branch)],
        },
        strategy="first",
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "x"})

    await proc.process(e, ctx)

    results = e.properties.get("parallel_results", {})
    assert results.get("fast") == {"branch": "fast"}
    assert "slow_done" not in call_log  # slow branch cancelled


@pytest.mark.asyncio
async def test_parallel_errors_collected() -> None:
    """Branch error → parallel_errors."""
    async def ok_branch(ex: Exchange[Any], ctx: Any) -> None:
        ex.out_message = Message(body={"ok": True})

    async def err_branch(ex: Exchange[Any], ctx: Any) -> None:
        raise RuntimeError("branch failed")

    proc = ParallelProcessor(
        branches={
            "ok": [_proc(ok_branch)],
            "err": [_proc(err_branch)],
        },
        strategy="all",
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "x"})

    await proc.process(e, ctx)

    results = e.properties.get("parallel_results", {})
    assert results.get("ok") == {"ok": True}
    errors = e.properties.get("parallel_errors", {})
    assert errors.get("err") == "branch failed"


@pytest.mark.asyncio
async def test_parallel_first_cancels_pending() -> None:
    """Pending tasks cancelled после first."""
    slow_completed: bool = False

    async def slow_branch(ex: Exchange[Any], ctx: Any) -> None:
        nonlocal slow_completed
        await asyncio.sleep(0.1)
        slow_completed = True
        ex.out_message = Message(body={"branch": "slow"})

    async def fast_branch(ex: Exchange[Any], ctx: Any) -> None:
        ex.out_message = Message(body={"branch": "fast"})

    proc = ParallelProcessor(
        branches={
            "slow": [_proc(slow_branch)],
            "fast": [_proc(fast_branch)],
        },
        strategy="first",
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "x"})

    await proc.process(e, ctx)

    # slow branch должна быть отменена ДО завершения
    assert slow_completed is False
    results = e.properties.get("parallel_results", {})
    assert results.get("fast") == {"branch": "fast"}


@pytest.mark.asyncio
async def test_parallel_body_copied_to_each_branch() -> None:
    """Каждый branch получает копию body."""
    branch_bodies: dict[str, Any] = {}

    async def capture_a(ex: Exchange[Any], ctx: Any) -> None:
        branch_bodies["a"] = ex.in_message.body

    async def capture_b(ex: Exchange[Any], ctx: Any) -> None:
        branch_bodies["b"] = ex.in_message.body

    proc = ParallelProcessor(
        branches={
            "a": [_proc(capture_a)],
            "b": [_proc(capture_b)],
        },
        strategy="all",
    )
    ctx = AsyncMock()
    e = _ex(body={"shared": "data", "unique": "input"})

    await proc.process(e, ctx)

    assert branch_bodies["a"] == {"shared": "data", "unique": "input"}
    assert branch_bodies["b"] == {"shared": "data", "unique": "input"}


# =============================================================================
# ChoiceProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_choice_first_matching_branch() -> None:
    """Первый matching выполняется, остальные пропускаются."""
    call_log: list[str] = []

    async def step_a(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("a")

    async def step_b(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("b")

    # Branch A: match "a" status; branch B: match "b" status — только A должен выполниться
    proc = ChoiceProcessor(
        when=[
            ChoiceBranch(expr="status == 'a'", processors=[_proc(step_a)]),
            ChoiceBranch(expr="status == 'b'", processors=[_proc(step_b)]),
        ],
    )
    ctx = AsyncMock()
    e = _ex(body={"status": "a"})

    await proc.process(e, ctx)

    assert call_log == ["a"]  # b не должна выполниться


@pytest.mark.asyncio
async def test_choice_otherwise_when_no_match() -> None:
    """Ни один expr не match → otherwise."""
    call_log: list[str] = []

    async def when_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("when")

    async def otherwise_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("otherwise")

    proc = ChoiceProcessor(
        when=[
            ChoiceBranch(expr="status == 'wrong'", processors=[_proc(when_step)]),
        ],
        otherwise=[_proc(otherwise_step)],
    )
    ctx = AsyncMock()
    e = _ex(body={"status": "other"})

    await proc.process(e, ctx)

    assert call_log == ["otherwise"]


@pytest.mark.asyncio
async def test_choice_jmespath_expr_matching() -> None:
    """JMESPath expr корректно матчит."""
    call_log: list[str] = []

    async def step_match(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("matched")

    proc = ChoiceProcessor(
        when=[
            ChoiceBranch(expr="data.items[0].active", processors=[_proc(step_match)]),
        ],
    )
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": [{"active": True}, {"active": False}]}})

    await proc.process(e, ctx)

    assert call_log == ["matched"]


@pytest.mark.asyncio
async def test_choice_no_match_no_otherwise() -> None:
    """No match + no otherwise → exchange unchanged."""
    async def when_step(ex: Exchange[Any], ctx: Any) -> None:
        ex.out_message = Message(body={"modified": True})

    # expr ищет несуществующий ключ → None (falsy)
    proc = ChoiceProcessor(
        when=[
            ChoiceBranch(expr="nonexistent", processors=[_proc(when_step)]),
        ],
        otherwise=None,
    )
    ctx = AsyncMock()
    e = _ex(body={"status": "other"})

    await proc.process(e, ctx)

    assert e.out_message is None
    assert e.status == ExchangeStatus.pending