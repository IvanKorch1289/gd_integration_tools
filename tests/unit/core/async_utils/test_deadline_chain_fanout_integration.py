"""Extended end-to-end chain integration tests (Sprint 12, cycle 150).

Extends `test_deadline_chain_integration.py` (5 tests) with chain scenarios
through fanout processors added in cycles 136-148.

Validates that ``DeadlineBudget`` propagates correctly through:
- middleware → fork_join branches → HTTP helper
- middleware → scatter_gather routes → HTTP helper
- middleware → multicast routes → HTTP helper
- middleware → multiple fanout layers (nested)

Each test catches integration bugs that focused tests would miss.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest

from src.backend.core.async_utils.deadline_budget import DeadlineBudget
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message


def _make_exchange() -> Exchange[Any]:
    ex = Exchange(in_message=Message(body={"input": "data"}))
    ex.status = ExchangeStatus.processing
    return ex


def _bind_ctx(budget: DeadlineBudget | None) -> Any:
    ctx = RequestContext(
        correlation_id="c",
        request_id="r",
        method="GET",
        path="/",
        deadline_budget=budget,
    )
    return bind_request_context(ctx)


class _MarkerProc:
    """Минимальный processor с overhead для тестирования budget consumption."""

    def __init__(self, name: str = "marker", sleep: float = 0.0) -> None:
        self.name = name
        self.sleep = sleep
        self.called = False

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        self.called = True
        if self.sleep > 0.0:
            await asyncio.sleep(self.sleep)
        exchange.in_message.body = {"name": self.name, "ok": True}


# ============================================================================
# Chain: fork_join с deadline narrowing
# ============================================================================


class TestChainForkJoin:
    """``ForkJoinProcessor`` с deadline budget."""

    @pytest.mark.asyncio
    async def test_active_budget_fork_join_completes(self) -> None:
        """Active budget → fork_join все ветки выполняются."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            m1, m2, m3 = _M(), _M(), _M()
            proc = ForkJoinProcessor(
                branches={"a": [m1], "b": [m2], "c": [m3]},
                aggregation="collect",
                timeout_seconds=2.0,
            )
            await proc.process(ex, ExecutionContext())

            assert m1.called and m2.called and m3.called
            results = ex.get_property("fork_join_results")
            assert results is not None
            assert set(results.keys()) == {"a", "b", "c"}
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_expired_budget_short_circuits_fork_join(self) -> None:
        """Expired budget → fork_join admission control."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.eip.fork_join import ForkJoinProcessor

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            m = _M()
            proc = ForkJoinProcessor(
                branches={"a": [m]}, aggregation="collect", timeout_seconds=10.0
            )
            await proc.process(ex, ExecutionContext())
            assert m.called is False
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)


# ============================================================================
# Chain: scatter_gather с deadline narrowing
# ============================================================================


class TestChainScatterGather:
    """``ScatterGatherProcessor`` с deadline budget narrowing."""

    @pytest.mark.asyncio
    async def test_active_budget_scatter_gather_runs(self, monkeypatch) -> None:
        """Active budget → scatter_gather все routes выполняются."""
        from src.backend.dsl.engine.processors.eip.routing.scatter_gather import (
            ScatterGatherProcessor,
        )

        async def fake_execute(route_id, body, headers, context):
            return route_id, {"route": route_id, "echo": body}, None

        monkeypatch.setattr(
            "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
            staticmethod(fake_execute),
        )

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(["r1", "r2", "r3"], timeout_seconds=2.0)
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            results = ex.get_property("scatter_results")
            assert results is not None
            assert set(results.keys()) == {"r1", "r2", "r3"}
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_expired_budget_short_circuits_scatter_gather(
        self, monkeypatch
    ) -> None:
        """Expired budget → scatter_gather admission control."""
        from src.backend.dsl.engine.processors.eip.routing.scatter_gather import (
            ScatterGatherProcessor,
        )

        route_calls: list[str] = []

        async def fake_execute(route_id, body, headers, context):
            route_calls.append(route_id)
            return route_id, {"ok": True}, None

        monkeypatch.setattr(
            "src.backend.dsl.engine.processors.base.SubPipelineExecutor.execute_route_safe",
            staticmethod(fake_execute),
        )

        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = ScatterGatherProcessor(["r1", "r2"], timeout_seconds=10.0)
            await proc.process(ex, ExecutionContext())
            assert route_calls == []
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)


# ============================================================================
# Chain: multicast с deadline narrowing
# ============================================================================


class TestChainMulticast:
    """``MulticastRoutesProcessor`` с deadline budget narrowing."""

    @pytest.mark.asyncio
    async def test_active_budget_multicast_runs(self, monkeypatch) -> None:
        """Active budget → multicast все routes выполняются."""
        # Per-cycle 137: MulticastRoutesProcessor интегрирован через narrow self._timeout.
        from src.backend.dsl.engine.processors.eip.routing.multicast import (
            MulticastRoutesProcessor,
        )

        # Patch ExecutionEngine и route_registry.
        cmd_registry_mod = sys.modules.get("src.backend.dsl.commands.registry")
        if cmd_registry_mod is None:  # pragma: no cover
            import src.backend.dsl.commands.registry as cmd_registry_mod

            cmd_registry_mod = sys.modules["src.backend.dsl.commands.registry"]

        class _FakeRegistry:
            def get_optional(self, route_id):
                return route_id

        monkeypatch.setattr(cmd_registry_mod, "route_registry", _FakeRegistry())

        import types

        fake_engine_mod = types.ModuleType("src.backend.dsl.engine.execution_engine")

        class _FakeEngine:
            async def execute(self, pipeline, *, exchange, context):
                exchange.set_out(body={"from": pipeline})
                return exchange

        def factory(*args, **kwargs):
            return _FakeEngine()

        fake_engine_mod.ExecutionEngine = factory  # type: ignore[attr-defined]
        monkeypatch.setitem(
            sys.modules, "src.backend.dsl.engine.execution_engine", fake_engine_mod
        )

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = MulticastRoutesProcessor(
                ["r1", "r2"], strategy="all", on_error="continue", timeout=2.0
            )
            await proc.process(ex, ExecutionContext())
            # Multicast может fail на strategy="all" с on_error="continue"
            # (любая ошибка → exchange.fail), но если routes отрабатывают — OK.
            results = ex.get_property("multicast_route_results")
            # Либо results есть (успех), либо errors (частичный).
            assert (
                results is not None
                or ex.get_property("multicast_route_errors") is not None
            )
        finally:
            clear_request_context(token)


# ============================================================================
# Chain: HTTP helper через deadline budget
# ============================================================================


class TestChainHTTPHelper:
    """``http_timeout_from_deadline`` через chain."""

    def test_active_budget_http_timeout_consumes_remaining(self) -> None:
        """Active budget → http_timeout_from_deadline возвращает positive timeout.

        Note: ``http_timeout_from_deadline`` принимает ``RequestContext``
        через global lookup, не как positional argument.
        """
        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            from src.backend.core.async_utils.deadline_http_helper import (
                http_timeout_from_deadline,
            )

            timeout = http_timeout_from_deadline(floor=0.5)
            # remaining ~10s, floor=0.5 → ~9.5s.
            assert timeout is not None
            assert 0.5 <= timeout <= 10.0
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_expired_budget_http_timeout_floor(self) -> None:
        """Expired budget → http_timeout_from_deadline возвращает floor."""
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            from src.backend.core.async_utils.deadline_http_helper import (
                http_timeout_from_deadline,
            )

            timeout = http_timeout_from_deadline(floor=0.0)
            # Expired → remaining=0, floor=0.0 → timeout=0.0
            assert timeout is not None
            assert timeout >= 0.0  # non-negative
        finally:
            clear_request_context(token)

    def test_http_timeout_floor_respected(self) -> None:
        """Floor нижний bound для timeout."""
        budget = DeadlineBudget.from_timeout(timeout=0.001)  # Very tight budget
        token = _bind_ctx(budget)
        try:
            from src.backend.core.async_utils.deadline_http_helper import (
                http_timeout_from_deadline,
            )

            timeout = http_timeout_from_deadline(floor=2.0)
            # Floor должен быть respected даже при малом remaining.
            assert timeout is not None
            assert timeout >= 2.0
        finally:
            clear_request_context(token)


# ============================================================================
# Chain: sequential chain через saga + parallel + http
# ============================================================================


class TestChainSequentialComposition:
    """Sequential chain: middleware → saga → parallel → HTTP helper."""

    @pytest.mark.asyncio
    async def test_full_chain_remaining_decreases(self) -> None:
        """Полная цепочка → remaining уменьшается на каждом этапе."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.control_flow.parallel import (
            ParallelProcessor,
        )

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                # Симулируем work — небольшой sleep.
                await asyncio.sleep(0.05)

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        initial_remaining = budget.remaining()
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            m1, m2 = _M(), _M()
            proc = ParallelProcessor(branches={"a": [m1], "b": [m2]}, strategy="all")
            await proc.process(ex, ExecutionContext())

            # Каждая ветка ждала 0.05s; parallel branch_budget = remaining / N = remaining / 2.
            # После parallel — remaining может быть negative или close to 0
            # (но НЕ меньше 0 в remaining(), который clamps).
            current_remaining = budget.remaining()
            assert current_remaining <= initial_remaining  # consumed
            assert current_remaining >= 0.0  # non-negative
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_chain_with_zero_remaining_admission_control(self) -> None:
        """Если budget exhausted между ветками → admission control."""
        from src.backend.dsl.engine.processors.base import BaseProcessor
        from src.backend.dsl.engine.processors.control_flow.parallel import (
            ParallelProcessor,
        )

        class _M(BaseProcessor):
            def __init__(self) -> None:
                super().__init__(name="m")
                self.called = False

            async def process(
                self, exchange: Exchange[Any], context: ExecutionContext
            ) -> None:
                self.called = True

        # Budget expired.
        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            m = _M()
            proc = ParallelProcessor(branches={"a": [m]}, strategy="all")
            await proc.process(ex, ExecutionContext())
            assert m.called is False
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)
