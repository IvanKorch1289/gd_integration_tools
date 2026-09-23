"""Focused tests for MulticastRoutesProcessor × DeadlineBudget integration (Sprint 12, ADR-0305).

Coverage:
    - Без deadline_budget: legacy path (использует ``self._timeout`` per-route).
    - С deadline_budget: ``effective_timeout = min(self._timeout, remaining)``
      пробрасывается в ``asyncio.wait_for`` внутри ``_run_route``.
    - Deadline уже истёк → ``exchange.fail()`` без fan-out (admission control).
    - Graceful degradation: ошибка доступа к RequestContext → legacy path.
    - DeadlineExpiredError пробрасывается (не маскируется).

Паттерн моков: подменяем ``route_registry`` и ``ExecutionEngine`` через
``monkeypatch.setitem(sys.modules, ...)`` — точно как существующий
``tests/unit/dsl/eip/test_multicast_routes.py``.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from src.backend.core.async_utils.deadline_budget import (
    DeadlineBudget,
    DeadlineExpiredError,
)
from src.backend.core.request_context import (
    RequestContext,
    bind_request_context,
    clear_request_context,
)
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.eip.routing import MulticastRoutesProcessor


class _FakeRouteRegistry:
    def __init__(self) -> None:
        self._routes: dict[str, Any] = {}

    def register(self, route_id: str, pipeline: Any) -> None:
        self._routes[route_id] = pipeline

    def get_optional(self, route_id: str) -> Any | None:
        return self._routes.get(route_id)


class _FakeEngine:
    def __init__(self) -> None:
        self.delays: dict[str, float] = {}
        self.results: dict[str, Any] = {}
        self.route_ids_seen: list[str] = []

    async def execute(
        self,
        pipeline: Any,
        *,
        exchange: Exchange[Any] | None = None,
        body: Any = None,
        headers: dict[str, Any] | None = None,
        context: ExecutionContext | None = None,
    ) -> Exchange[Any]:
        route_id = pipeline  # pipeline-marker == route_id
        self.route_ids_seen.append(route_id)
        if route_id in self.delays:
            await asyncio.sleep(self.delays[route_id])
        result = self.results.get(route_id, {"ok": route_id})
        assert exchange is not None
        exchange.set_out(body=result)
        return exchange


@pytest.fixture
def patched_multicast(monkeypatch: pytest.MonkeyPatch):
    """Подменяет route_registry и ExecutionEngine в модуле multicast."""
    fake_registry = _FakeRouteRegistry()
    fake_registry.register("r1", "r1")
    fake_registry.register("r2", "r2")
    fake_registry.register("slow", "slow")

    cmd_registry_mod = sys.modules.get("src.backend.dsl.commands.registry")
    if cmd_registry_mod is None:  # pragma: no cover
        import src.backend.dsl.commands.registry as cmd_registry_mod

        cmd_registry_mod = sys.modules["src.backend.dsl.commands.registry"]
    monkeypatch.setattr(cmd_registry_mod, "route_registry", fake_registry)

    fake_engine = _FakeEngine()
    fake_engine_holder: dict[str, _FakeEngine] = {"engine": fake_engine}

    fake_engine_mod = types.ModuleType("src.backend.dsl.engine.execution_engine")

    def _engine_factory(*args: Any, **kwargs: Any) -> _FakeEngine:
        return fake_engine_holder["engine"]

    fake_engine_mod.ExecutionEngine = _engine_factory  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "src.backend.dsl.engine.execution_engine", fake_engine_mod
    )

    return fake_registry, fake_engine_holder


def _make_exchange() -> Exchange[Any]:
    ex = Exchange(in_message=Message(body={"x": 1}))
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


class TestMulticastWithoutDeadline:
    """Legacy path: без deadline_budget — используется self._timeout."""

    @pytest.mark.asyncio
    async def test_no_deadline_routes_complete(self, patched_multicast: Any) -> None:
        fake_registry, fake_engine_holder = patched_multicast
        fake_engine_holder["engine"].delays = {"r1": 0.01, "r2": 0.01}

        ex = _make_exchange()
        proc = MulticastRoutesProcessor(
            ["r1", "r2"], strategy="all", on_error="continue", timeout=1.0
        )
        await proc.process(ex, ExecutionContext())
        assert ex.error is None
        results = ex.get_property("multicast_route_results")
        assert set(results.keys()) == {"r1", "r2"}


class TestMulticastWithDeadline:
    """С deadline_budget: per-route timeout narrowed на remaining."""

    @pytest.mark.asyncio
    async def test_deadline_tighter_than_own_timeout(
        self, patched_multicast: Any
    ) -> None:
        """remaining < self._timeout → route прерывается по deadline."""
        fake_registry, fake_engine_holder = patched_multicast
        # slow route засыпает на 5s; с deadline remaining ~0.05s — должно прерваться.
        fake_engine_holder["engine"].delays = {"slow": 5.0}

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        await asyncio.sleep(0.05)
        budget_after = budget.share(0.005)  # ~0.05s remaining
        token = _bind_ctx(budget_after)
        try:
            ex = _make_exchange()
            proc = MulticastRoutesProcessor(
                ["slow"], strategy="all", on_error="continue", timeout=10.0
            )
            await proc.process(ex, ExecutionContext())
            errors = ex.get_property("multicast_route_errors")
            assert errors is not None
            assert "slow" in errors
            assert (
                "таймаут" in errors["slow"].lower()
                or "timeout" in errors["slow"].lower()
            )
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_deadline_looser_uses_own_timeout(
        self, patched_multicast: Any
    ) -> None:
        """remaining > self._timeout → используется self._timeout (без изменений)."""
        fake_registry, fake_engine_holder = patched_multicast
        fake_engine_holder["engine"].delays = {"r1": 0.01, "r2": 0.01}

        budget = DeadlineBudget.from_timeout(timeout=10.0)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = MulticastRoutesProcessor(
                ["r1", "r2"], strategy="all", on_error="continue", timeout=1.0
            )
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            results = ex.get_property("multicast_route_results")
            assert set(results.keys()) == {"r1", "r2"}
        finally:
            clear_request_context(token)


class TestMulticastAdmissionControl:
    """Deadline истёк на входе — exchange.fail() без fan-out."""

    @pytest.mark.asyncio
    async def test_expired_budget_skips_fan_out(self, patched_multicast: Any) -> None:
        """Budget remaining <= 0 → admission control."""
        fake_registry, fake_engine_holder = patched_multicast
        engine = fake_engine_holder["engine"]
        engine.delays = {}

        budget = DeadlineBudget.from_timeout(timeout=1.0)
        await asyncio.sleep(1.2)
        token = _bind_ctx(budget)
        try:
            ex = _make_exchange()
            proc = MulticastRoutesProcessor(
                ["r1", "r2"], strategy="all", on_error="continue", timeout=10.0
            )
            await proc.process(ex, ExecutionContext())
            # routes не должны быть запущены
            assert engine.route_ids_seen == []
            assert ex.error is not None
            assert "deadline" in ex.error.lower() or "skipped" in ex.error.lower()
        finally:
            clear_request_context(token)


class TestMulticastGracefulDegradation:
    """Ошибка доступа к RequestContext не ломает multicast."""

    @pytest.mark.asyncio
    async def test_missing_context_falls_back_to_legacy(
        self, patched_multicast: Any
    ) -> None:
        """Без RequestContext → self._timeout используется как обычно."""
        fake_registry, fake_engine_holder = patched_multicast
        fake_engine_holder["engine"].delays = {"r1": 0.01, "r2": 0.01}

        ex = _make_exchange()
        proc = MulticastRoutesProcessor(
            ["r1", "r2"], strategy="all", on_error="continue", timeout=1.0
        )
        await proc.process(ex, ExecutionContext())
        assert ex.error is None
        results = ex.get_property("multicast_route_results")
        assert set(results.keys()) == {"r1", "r2"}

    @pytest.mark.asyncio
    async def test_context_without_budget_uses_legacy(
        self, patched_multicast: Any
    ) -> None:
        """Контекст есть, но deadline_budget=None → legacy."""
        fake_registry, fake_engine_holder = patched_multicast
        fake_engine_holder["engine"].delays = {"r1": 0.01}

        token = _bind_ctx(None)
        try:
            ex = _make_exchange()
            proc = MulticastRoutesProcessor(
                ["r1"], strategy="all", on_error="continue", timeout=1.0
            )
            await proc.process(ex, ExecutionContext())
            assert ex.error is None
            assert "r1" in (ex.get_property("multicast_route_results") or {})
        finally:
            clear_request_context(token)

    @pytest.mark.asyncio
    async def test_context_access_error_falls_back_to_legacy(
        self, patched_multicast: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если RequestContext.current() падает → multicast не ломается."""
        import src.backend.core.request_context as ctx_mod

        def boom() -> None:
            raise RuntimeError("context broken")

        monkeypatch.setattr(
            ctx_mod, "RequestContext", types.SimpleNamespace(current=boom)
        )

        fake_registry, fake_engine_holder = patched_multicast
        fake_engine_holder["engine"].delays = {"r1": 0.01}

        ex = _make_exchange()
        proc = MulticastRoutesProcessor(
            ["r1"], strategy="all", on_error="continue", timeout=1.0
        )
        await proc.process(ex, ExecutionContext())
        assert ex.error is None
        assert "r1" in (ex.get_property("multicast_route_results") or {})


class TestMulticastDeadlineExceptions:
    """DeadlineExpiredError пробрасывается, не маскируется."""

    @pytest.mark.asyncio
    async def test_deadline_expired_error_propagates(
        self, patched_multicast: Any
    ) -> None:
        """Если ``budget.remaining()`` бросает ``DeadlineExpiredError`` — он пробрасывается."""

        # Подкласс, который raises DeadlineExpiredError из .remaining().
        class _BoomBudget(DeadlineBudget):
            def remaining(self, *, now: float | None = None) -> float:
                raise DeadlineExpiredError(
                    "forced for test", original_timeout=self.original_timeout
                )

        boom_budget = _BoomBudget(deadline_ts=0.0, original_timeout=1.0)

        token = bind_request_context(
            RequestContext(
                correlation_id="c",
                request_id="r",
                method="GET",
                path="/",
                deadline_budget=boom_budget,
            )
        )
        try:
            ex = _make_exchange()
            proc = MulticastRoutesProcessor(
                ["r1"], strategy="all", on_error="continue", timeout=10.0
            )
            # DeadlineExpiredError должен пробрасываться через `except DeadlineExpiredError: raise`.
            with pytest.raises(DeadlineExpiredError):
                await proc.process(ex, ExecutionContext())
        finally:
            clear_request_context(token)
