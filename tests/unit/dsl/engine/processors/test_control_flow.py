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
from src.backend.dsl.engine.processors.base import BaseProcessor, CallableProcessor
from src.backend.dsl.engine.processors.control_flow import (
    ChoiceBranch,
    ChoiceProcessor,
    ParallelProcessor,
    PipelineRefProcessor,
    RetryProcessor,
    SagaProcessor,
    SagaStep,
    TryCatchProcessor,
)
from src.backend.dsl.engine.processors.eip.flow_control import (
    ForEachProcessor,
    ThrottlerProcessor,
)
from src.backend.dsl.engine.processors.eip.resilience import CircuitBreakerProcessor


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


def _proc(fn: Callable[..., Any]) -> CallableProcessor:
    """Оборачивает async fn в CallableProcessor."""
    return CallableProcessor(fn)


class _DummySpecProcessor(BaseProcessor):
    """Процессор с поддержкой to_spec для тестов сериализации."""

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name=name or "dummy_spec")

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        pass

    def to_spec(self) -> dict[str, Any] | None:
        return {"dummy": {"name": self.name}}


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
        try_processors=[_proc(try_step)], catch_processors=[_proc(catch_step)]
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
        try_processors=[_proc(failing_try)], catch_processors=[_proc(catch_step)]
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

    proc = TryCatchProcessor(try_processors=[_proc(failing_try)], catch_processors=[])
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
        try_processors=[_proc(fail_exchange)], catch_processors=[_proc(catch_step)]
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
        branches={"a": [_proc(branch_a)], "b": [_proc(branch_b)]}, strategy="all"
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
        branches={"slow": [_proc(slow_branch)], "fast": [_proc(fast_branch)]},
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
        branches={"ok": [_proc(ok_branch)], "err": [_proc(err_branch)]}, strategy="all"
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
        branches={"slow": [_proc(slow_branch)], "fast": [_proc(fast_branch)]},
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
        branches={"a": [_proc(capture_a)], "b": [_proc(capture_b)]}, strategy="all"
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
        ]
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
        when=[ChoiceBranch(expr="status == 'wrong'", processors=[_proc(when_step)])],
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
        when=[ChoiceBranch(expr="data.items[0].active", processors=[_proc(step_match)])]
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
        when=[ChoiceBranch(expr="nonexistent", processors=[_proc(when_step)])],
        otherwise=None,
    )
    ctx = AsyncMock()
    e = _ex(body={"status": "other"})

    await proc.process(e, ctx)

    assert e.out_message is None
    assert e.status == ExchangeStatus.pending


# =============================================================================
# ForEachProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_for_each_iterates_over_items() -> None:
    """ForEach iterates over items, sets body to each item, collects results."""
    call_log: list[Any] = []

    async def process_item(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append(ex.in_message.body)
        ex.out_message = Message(body={"processed": ex.in_message.body})

    proc = ForEachProcessor(
        items_path="data.items", processors=[_proc(process_item)], copy_exchange=True
    )
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": [1, 2, 3]}})

    await proc.process(e, ctx)

    assert call_log == [1, 2, 3]
    assert e.properties.get("for_each_results") == [
        {"processed": 1},
        {"processed": 2},
        {"processed": 3},
    ]
    assert e.properties.get("for_each_count") == 3


@pytest.mark.asyncio
async def test_for_each_empty_list() -> None:
    """ForEach with empty list → no iterations, empty results."""

    async def process_item(ex: Exchange[Any], ctx: Any) -> None:
        pass

    proc = ForEachProcessor(items_path="data.items", processors=[_proc(process_item)])
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": []}})

    await proc.process(e, ctx)

    assert e.properties.get("for_each_results") == []
    assert e.properties.get("for_each_count") == 0


@pytest.mark.asyncio
async def test_for_each_max_iterations() -> None:
    """ForEach respects max_iterations limit."""
    call_log: list[Any] = []

    async def process_item(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append(ex.in_message.body)

    proc = ForEachProcessor(
        items_path="data.items", processors=[_proc(process_item)], max_iterations=2
    )
    ctx = AsyncMock()
    e = _ex(body={"data": {"items": [1, 2, 3, 4, 5]}})

    await proc.process(e, ctx)

    # Only first 2 items processed due to max_iterations
    assert call_log == [1, 2]
    assert e.properties.get("for_each_count") == 2
    assert e.properties.get("for_each_results") == [1, 2]


# =============================================================================
# RetryProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_retry_success_first_attempt() -> None:
    """First attempt succeeds → no retry needed."""
    call_log: list[int] = []

    async def succeed_once(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append(1)
        ex.out_message = Message(body={"status": "ok"})

    proc = RetryProcessor(
        processors=[_proc(succeed_once)], max_attempts=3, delay_seconds=0.01
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == [1]
    assert e.out_message.body == {"status": "ok"}
    # On success, exchange remains in its initial pending state
    assert e.status == ExchangeStatus.pending


@pytest.mark.asyncio
async def test_retry_eventually_succeeds() -> None:
    """Fails twice, succeeds on third attempt."""
    call_log: list[int] = []

    async def fail_twice(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append(len(call_log) + 1)
        if len(call_log) < 3:
            raise RuntimeError(f"attempt {len(call_log)}")
        ex.out_message = Message(body={"status": "ok"})

    proc = RetryProcessor(
        processors=[_proc(fail_twice)],
        max_attempts=3,
        delay_seconds=0.01,
        backoff="fixed",
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == [1, 2, 3]
    assert e.out_message.body == {"status": "ok"}


@pytest.mark.asyncio
async def test_retry_all_attempts_fail() -> None:
    """All attempts fail → exchange marked as failed."""
    call_log: list[int] = []

    async def always_fail(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append(len(call_log) + 1)
        ex.fail(f"attempt {len(call_log)} failed")

    proc = RetryProcessor(
        processors=[_proc(always_fail)],
        max_attempts=3,
        delay_seconds=0.01,
        backoff="fixed",
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == [1, 2, 3]
    assert e.status == ExchangeStatus.failed
    assert "All 3 attempts failed" in (e.error or "")


@pytest.mark.asyncio
async def test_retry_exponential_backoff() -> None:
    """Retry uses exponential backoff when configured."""
    import time

    call_times: list[float] = []

    async def log_time(ex: Exchange[Any], ctx: Any) -> None:
        call_times.append(time.monotonic())
        if len(call_times) < 2:
            ex.fail("retry")
        else:
            ex.out_message = Message(body={"status": "ok"})

    proc = RetryProcessor(
        processors=[_proc(log_time)],
        max_attempts=2,
        delay_seconds=0.05,
        backoff="exponential",
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert len(call_times) == 2
    # Exponential backoff: second delay should be roughly 2x first
    delay = call_times[1] - call_times[0]
    assert delay >= 0.04  # at least 80% of expected 0.05s minimum


# =============================================================================
# SagaProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_saga_all_steps_succeed() -> None:
    """All saga steps complete → saga_completed=True."""
    call_log: list[str] = []

    async def step1(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("step1")
        ex.out_message = Message(body={"step1": "done"})

    async def step2(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("step2")
        ex.out_message = Message(body={"step2": "done"})

    proc = SagaProcessor(
        steps=[SagaStep(forward=_proc(step1)), SagaStep(forward=_proc(step2))]
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == ["step1", "step2"]
    assert e.properties.get("saga_completed") is True
    # On success, exchange remains in its initial pending state
    assert e.status == ExchangeStatus.pending


@pytest.mark.asyncio
async def test_saga_compensation_on_failure() -> None:
    """Step 2 fails → step 1 compensated in reverse order."""
    call_log: list[str] = []

    async def step1(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("step1")
        ex.out_message = Message(body={"step1": "done"})

    async def compensate1(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("compensate1")

    async def step2(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("step2")
        raise RuntimeError("step2 failed")

    proc = SagaProcessor(
        steps=[
            SagaStep(forward=_proc(step1), compensate=_proc(compensate1)),
            SagaStep(forward=_proc(step2)),
        ]
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == ["step1", "step2", "compensate1"]
    assert e.properties.get("saga_failed_step") == 1
    assert e.status == ExchangeStatus.failed


@pytest.mark.asyncio
async def test_saga_no_compensate_step() -> None:
    """Step without compensation → no-op on rollback."""
    call_log: list[str] = []

    async def step1(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("step1")

    async def step2(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("step2")
        raise RuntimeError("fail")

    proc = SagaProcessor(
        steps=[
            SagaStep(forward=_proc(step1)),  # no compensation
            SagaStep(forward=_proc(step2)),
        ]
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    await proc.process(e, ctx)

    assert call_log == ["step1", "step2"]
    assert e.properties.get("saga_failed_step") == 1


# =============================================================================
# PipelineRefProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_pipeline_ref_stores_result() -> None:
    """PipelineRefProcessor stores sub-pipeline result in property."""
    # Mock the SubPipelineExecutor
    from unittest.mock import patch

    async def dummy_route(
        body: Any, headers: dict[str, Any], ctx: Any
    ) -> tuple[Any, str | None]:
        return {"sub_result": body["value"] * 2}, None

    proc = PipelineRefProcessor(route_id="test_route", result_property="my_result")
    ctx = AsyncMock()
    e = _ex(body={"value": 5})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = ({"sub_result": 10}, None)
        await proc.process(e, ctx)

    assert e.properties.get("my_result") == {"sub_result": 10}


@pytest.mark.asyncio
async def test_pipeline_ref_forwards_error() -> None:
    """PipelineRefProcessor forwards sub-pipeline error to exchange."""
    from unittest.mock import patch

    proc = PipelineRefProcessor(route_id="failing_route", result_property="result")
    ctx = AsyncMock()
    e = _ex(body={"value": 5})

    with patch(
        "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route",
        new_callable=AsyncMock,
    ) as mock_exec:
        mock_exec.return_value = (None, "sub-pipeline failed")
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    assert "failing_route" in (e.error or "")
    assert "sub-pipeline failed" in (e.error or "")


# =============================================================================
# ThrottlerProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_throttler_allows_burst() -> None:
    """Throttler allows burst size requests to pass immediately without sleeping."""
    import time

    proc = ThrottlerProcessor(rate=10.0, burst=3)
    ctx = AsyncMock()

    # First 3 should pass without delay - measure time
    start = time.monotonic()
    for i in range(3):
        e = _ex(body={"i": i})
        await proc.process(e, ctx)
    elapsed = time.monotonic() - start

    # Should complete almost instantly (no sleep for burst within limit)
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_throttler_enforces_rate_after_burst() -> None:
    """Throttler enforces rate limit after burst is exhausted."""
    import time

    # rate=2/s, burst=1
    proc = ThrottlerProcessor(rate=2.0, burst=1)
    ctx = AsyncMock()

    start = time.monotonic()
    e1 = _ex(body={"i": 1})
    await proc.process(e1, ctx)

    e2 = _ex(body={"i": 2})
    await proc.process(e2, ctx)
    elapsed = time.monotonic() - start

    # At 2/s, gap between calls should be ~0.5s
    # Allow some tolerance: at least 0.3s
    assert elapsed >= 0.3


# =============================================================================
# CircuitBreakerProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_success() -> None:
    """CircuitBreaker allows successful calls through."""
    from unittest.mock import AsyncMock, MagicMock, patch

    class DummyGuard:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def process(ex: Exchange[Any], ctx: Any) -> None:
        ex.out_message = Message(body={"status": "ok"})

    proc = CircuitBreakerProcessor(
        processors=[_proc(process)], failure_threshold=5, recovery_timeout=30.0
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    mock_breaker = MagicMock()
    mock_breaker.state = "closed"
    # guard is an async method that returns an async context manager
    mock_breaker.guard = MagicMock(return_value=DummyGuard())

    # Patch where get_breaker_registry is imported from (inside process method)
    with patch(
        "src.backend.core.resilience.breaker.get_breaker_registry"
    ) as mock_registry:
        mock_registry.return_value.get_or_create.return_value = mock_breaker
        await proc.process(e, ctx)

    assert e.out_message.body == {"status": "ok"}
    assert e.properties.get("cb_state") == "closed"


@pytest.mark.asyncio
async def test_circuit_breaker_open_calls_fallback() -> None:
    """CircuitBreaker OPEN → fallback processors executed."""
    from unittest.mock import MagicMock, patch

    from src.backend.core.resilience.breaker import CircuitOpen

    call_log: list[str] = []

    async def fallback_step(ex: Exchange[Any], ctx: Any) -> None:
        call_log.append("fallback")

    class OpenBreakerGuard:
        async def __aenter__(self):
            raise CircuitOpen("breaker is open")

        async def __aexit__(self, *args):
            pass

    proc = CircuitBreakerProcessor(
        processors=[_proc(lambda ex, ctx: None)],
        fallback_processors=[_proc(fallback_step)],
        failure_threshold=5,
    )
    ctx = AsyncMock()
    e = _ex(body={"input": "test"})

    mock_breaker = MagicMock()
    mock_breaker.state = "open"
    mock_breaker.guard = MagicMock(return_value=OpenBreakerGuard())

    with patch(
        "src.backend.core.resilience.breaker.get_breaker_registry"
    ) as mock_registry:
        mock_registry.return_value.get_or_create.return_value = mock_breaker
        await proc.process(e, ctx)

    assert call_log == ["fallback"]
    assert e.properties.get("cb_state") == "open_fallback"


# =============================================================================
# ChoiceBranch validation
# =============================================================================


def test_choice_branch_requires_exactly_one_condition() -> None:
    """ChoiceBranch требует ровно одно из predicate / expr."""
    with pytest.raises(ValueError, match="ровно одно"):
        ChoiceBranch(processors=[], predicate=None, expr=None)

    with pytest.raises(ValueError, match="ровно одно"):
        ChoiceBranch(processors=[], predicate=lambda ex: True, expr="status == 'ok'")


def test_choice_branch_predicate_matches() -> None:
    """predicate-ветка матчит через callable."""
    branch = ChoiceBranch(
        processors=[], predicate=lambda ex: ex.in_message.body.get("ok") is True
    )
    e = _ex(body={"ok": True})
    assert branch.matches(e) is True

    e2 = _ex(body={"ok": False})
    assert branch.matches(e2) is False


# =============================================================================
# _normalize_choice_branches
# =============================================================================


def test_normalize_choice_branches_tuple() -> None:
    """Legacy tuple (predicate, processors) → ChoiceBranch."""
    from src.backend.dsl.engine.processors.control_flow import (
        _normalize_choice_branches,
    )

    def _pred(ex: Exchange[Any]) -> bool:
        return True

    pred = _pred
    procs = [CallableProcessor(lambda e, c: None)]
    result = _normalize_choice_branches([(pred, procs)])
    assert len(result) == 1
    assert result[0].predicate is pred
    # _normalize_choice_branches делает list(processors) → копия списка
    assert result[0].processors == procs


def test_normalize_choice_branches_invalid() -> None:
    """Invalid item → ValueError."""
    from src.backend.dsl.engine.processors.control_flow import (
        _normalize_choice_branches,
    )

    with pytest.raises(ValueError, match="Invalid choice-branch"):
        _normalize_choice_branches(["bad_item"])


# =============================================================================
# to_spec round-trip serialization
# =============================================================================


def test_choice_to_spec_with_expr() -> None:
    """ChoiceProcessor с JMESPath-ветками сериализуется."""
    proc = ChoiceProcessor(
        when=[
            ChoiceBranch(
                expr="status == 'ok'", processors=[_DummySpecProcessor("when_p")]
            )
        ],
        otherwise=[_DummySpecProcessor("otherwise_p")],
    )
    spec = proc.to_spec()
    assert spec is not None
    assert "choice" in spec
    assert spec["choice"]["when"][0]["expr"] == "status == 'ok'"


def test_choice_to_spec_with_predicate_returns_none() -> None:
    """ChoiceProcessor с callable-predicate → None (не сериализуется)."""
    proc = ChoiceProcessor(
        when=[
            ChoiceBranch(
                predicate=lambda ex: True,
                processors=[CallableProcessor(lambda e, c: None)],
            )
        ]
    )
    assert proc.to_spec() is None


def test_try_catch_to_spec() -> None:
    """TryCatchProcessor сериализуется корректно."""
    proc = TryCatchProcessor(
        try_processors=[_DummySpecProcessor("try_p")],
        catch_processors=[_DummySpecProcessor("catch_p")],
        finally_processors=[_DummySpecProcessor("finally_p")],
    )
    spec = proc.to_spec()
    assert spec is not None
    assert "do_try" in spec
    assert "try_processors" in spec["do_try"]
    assert "catch_processors" in spec["do_try"]
    assert "finally_processors" in spec["do_try"]


def test_retry_to_spec() -> None:
    """RetryProcessor сериализуется корректно."""
    proc = RetryProcessor(
        processors=[_DummySpecProcessor("retry_p")],
        max_attempts=5,
        delay_seconds=2.0,
        backoff="exponential",
        jitter_seconds=0.5,
    )
    spec = proc.to_spec()
    assert spec is not None
    assert "retry" in spec
    assert spec["retry"]["max_attempts"] == 5
    assert spec["retry"]["jitter_seconds"] == 0.5


def test_parallel_to_spec() -> None:
    """ParallelProcessor сериализуется корректно."""
    proc = ParallelProcessor(
        branches={"a": [_DummySpecProcessor("a_p")], "b": [_DummySpecProcessor("b_p")]},
        strategy="all",
    )
    spec = proc.to_spec()
    assert spec is not None
    assert "parallel" in spec
    assert spec["parallel"]["strategy"] == "all"
    assert "a" in spec["parallel"]["branches"]


def test_saga_to_spec() -> None:
    """SagaProcessor сериализуется корректно."""
    fwd = _DummySpecProcessor("fwd_p")
    comp = _DummySpecProcessor("comp_p")
    proc = SagaProcessor(steps=[SagaStep(forward=fwd, compensate=comp)])
    spec = proc.to_spec()
    assert spec is not None
    assert "saga" in spec
    assert len(spec["saga"]["steps"]) == 1
    assert "forward" in spec["saga"]["steps"][0]
    assert "compensate" in spec["saga"]["steps"][0]


def test_pipeline_ref_to_spec() -> None:
    """PipelineRefProcessor не поддерживает сериализацию → None."""
    proc = PipelineRefProcessor(route_id="my_route")
    assert proc.to_spec() is None
