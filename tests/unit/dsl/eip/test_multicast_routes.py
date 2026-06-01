"""Unit-тесты MulticastRoutesProcessor (Wave 18.U3).

Покрытие:
    * strategy=all + on_error=continue: собирает все результаты, отдельные
      ошибки не валят exchange.
    * strategy=all + on_error=fail: первая ошибка → exchange.fail().
    * strategy=first_success: останавливается после первого успеха.
    * Таймаут отдельного маршрута → записывается как ошибка.
    * Незарегистрированный route_id → ошибка ``"не зарегистрирован"``.
    * Валидация конструктора (strategy / on_error).
    * to_spec() round-trip.
"""
# ruff: noqa: S101

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.routing import MulticastRoutesProcessor

# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------


def _make_exchange(body: Any = None) -> Exchange:
    return Exchange(in_message=Message(body=body or {}))


def _make_context() -> ExecutionContext:
    return ExecutionContext(route_id="multicast-test")


class _FakeRouteRegistry:
    """Минимальный реестр маршрутов: ``{route_id: marker_obj}``."""

    def __init__(self) -> None:
        self._routes: dict[str, Any] = {}

    def register(self, route_id: str, pipeline: Any) -> None:
        self._routes[route_id] = pipeline

    def get_optional(self, route_id: str) -> Any | None:
        return self._routes.get(route_id)


class _FakeEngine:
    """Имитация ``DSLExecutionEngine`` для тестов: задаваемое поведение по route."""

    def __init__(
        self,
        *,
        results: dict[str, dict[str, Any]] | None = None,
        delays: dict[str, float] | None = None,
        errors: dict[str, str] | None = None,
        raises: dict[str, Exception] | None = None,
    ) -> None:
        self.results = results or {}
        self.delays = delays or {}
        self.errors = errors or {}
        self.raises = raises or {}

    def __call__(self, *, route_registry: Any) -> _FakeEngine:  # noqa: ARG002
        # Имитирует конструктор DSLExecutionEngine(route_registry=...)
        return self

    async def run_pipeline(
        self, pipeline: Any, exchange: Exchange, context: ExecutionContext
    ) -> None:  # noqa: ARG002
        # Определяем, к какому route_id относится pipeline.
        route_id = pipeline  # в тестах pipeline-маркер == route_id
        if route_id in self.delays:
            await asyncio.sleep(self.delays[route_id])
        if route_id in self.raises:
            raise self.raises[route_id]
        if route_id in self.errors:
            exchange.fail(self.errors[route_id])
            return
        body = self.results.get(route_id, {"ok": route_id})
        exchange.set_out(body=body)


@pytest.fixture
def patched_routing(monkeypatch: pytest.MonkeyPatch):
    """Подменяет ``route_registry`` и ``DSLExecutionEngine`` в routing-модуле.

    MulticastRoutesProcessor делает локальные ``from ... import ...``
    внутри ``process()``; патчим целевые модули в ``sys.modules``.
    """
    fake_registry = _FakeRouteRegistry()

    # Подменяем src.dsl.commands.registry.route_registry.
    cmd_registry_mod = sys.modules.get("src.backend.dsl.commands.registry")
    if cmd_registry_mod is None:  # pragma: no cover
        import src.backend.dsl.commands.registry as cmd_registry_mod  # noqa: F401

        cmd_registry_mod = sys.modules["src.backend.dsl.commands.registry"]
    monkeypatch.setattr(cmd_registry_mod, "route_registry", fake_registry)

    # Подменяем src.dsl.engine.execution_engine с DSLExecutionEngine.
    fake_engine_holder: dict[str, _FakeEngine] = {}

    fake_engine_mod = types.ModuleType("src.backend.dsl.engine.execution_engine")

    def _engine_factory(*, route_registry: Any):  # noqa: ARG001
        return fake_engine_holder["engine"]

    fake_engine_mod.DSLExecutionEngine = _engine_factory  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules, "src.backend.dsl.engine.execution_engine", fake_engine_mod
    )

    return fake_registry, fake_engine_holder


# ---------------------------------------------------------------------------
# strategy=all
# ---------------------------------------------------------------------------


async def test_strategy_all_collects_all_results(patched_routing) -> None:
    """strategy=all: все маршруты выполняются, результаты в multicast_route_results."""
    registry, engine_holder = patched_routing
    registry.register("a", "a")
    registry.register("b", "b")
    engine_holder["engine"] = _FakeEngine(
        results={"a": {"r": "A"}, "b": {"r": "B"}}
    )

    proc = MulticastRoutesProcessor(["a", "b"], strategy="all", on_error="continue")
    ex = _make_exchange()
    await proc.process(ex, _make_context())

    results = ex.get_property("multicast_route_results")
    assert results == {"a": {"r": "A"}, "b": {"r": "B"}}
    assert ex.error is None


async def test_strategy_all_on_error_continue_keeps_going(patched_routing) -> None:
    """on_error=continue: ошибка в одном маршруте не валит весь multicast."""
    registry, engine_holder = patched_routing
    registry.register("good", "good")
    registry.register("bad", "bad")
    engine_holder["engine"] = _FakeEngine(
        results={"good": {"v": 1}}, errors={"bad": "boom"}
    )

    proc = MulticastRoutesProcessor(
        ["good", "bad"], strategy="all", on_error="continue"
    )
    ex = _make_exchange()
    await proc.process(ex, _make_context())

    assert ex.get_property("multicast_route_results") == {"good": {"v": 1}}
    errs = ex.get_property("multicast_route_errors")
    assert errs == {"bad": "boom"}
    assert ex.error is None  # exchange не упал


async def test_strategy_all_on_error_fail_propagates(patched_routing) -> None:
    """on_error=fail: первая ошибка маршрута → exchange.fail()."""
    registry, engine_holder = patched_routing
    registry.register("bad", "bad")
    engine_holder["engine"] = _FakeEngine(errors={"bad": "fatal"})

    proc = MulticastRoutesProcessor(["bad"], strategy="all", on_error="fail")
    ex = _make_exchange()
    await proc.process(ex, _make_context())

    assert ex.error is not None
    assert "bad" in ex.error
    assert "fatal" in ex.error


# ---------------------------------------------------------------------------
# strategy=first_success
# ---------------------------------------------------------------------------


async def test_strategy_first_success_returns_first_done(patched_routing) -> None:
    """first_success: возвращается первый успешный результат."""
    registry, engine_holder = patched_routing
    registry.register("fast", "fast")
    registry.register("slow", "slow")
    engine_holder["engine"] = _FakeEngine(
        results={"fast": {"f": 1}, "slow": {"s": 2}},
        delays={"slow": 0.5},
    )

    proc = MulticastRoutesProcessor(
        ["fast", "slow"], strategy="first_success"
    )
    ex = _make_exchange()
    await proc.process(ex, _make_context())

    results = ex.get_property("multicast_route_results") or {}
    # Должен попасть только один (первый success).
    assert len(results) == 1
    assert "fast" in results


# ---------------------------------------------------------------------------
# Таймаут
# ---------------------------------------------------------------------------


async def test_timeout_records_error(patched_routing) -> None:
    """Таймаут маршрута → запись в multicast_route_errors."""
    registry, engine_holder = patched_routing
    registry.register("slow", "slow")
    engine_holder["engine"] = _FakeEngine(delays={"slow": 0.5})

    proc = MulticastRoutesProcessor(
        ["slow"], strategy="all", on_error="continue", timeout=0.05
    )
    ex = _make_exchange()
    await proc.process(ex, _make_context())

    errs = ex.get_property("multicast_route_errors") or {}
    assert "slow" in errs
    assert "Таймаут" in errs["slow"]


# ---------------------------------------------------------------------------
# Незарегистрированный route_id
# ---------------------------------------------------------------------------


async def test_unregistered_route_recorded_as_error(patched_routing) -> None:
    """Маршрут отсутствует в registry → ошибка ``не зарегистрирован``."""
    _registry, engine_holder = patched_routing
    engine_holder["engine"] = _FakeEngine()

    proc = MulticastRoutesProcessor(
        ["missing"], strategy="all", on_error="continue"
    )
    ex = _make_exchange()
    await proc.process(ex, _make_context())

    errs = ex.get_property("multicast_route_errors") or {}
    assert "missing" in errs
    assert "не зарегистрирован" in errs["missing"]


# ---------------------------------------------------------------------------
# Валидация конструктора
# ---------------------------------------------------------------------------


def test_invalid_strategy_raises() -> None:
    """Неверный strategy → ValueError."""
    with pytest.raises(ValueError, match="strategy"):
        MulticastRoutesProcessor(["r"], strategy="bogus")


def test_invalid_on_error_raises() -> None:
    """Неверный on_error → ValueError."""
    with pytest.raises(ValueError, match="on_error"):
        MulticastRoutesProcessor(["r"], on_error="abandon")


# ---------------------------------------------------------------------------
# to_spec round-trip
# ---------------------------------------------------------------------------


def test_to_spec_round_trip() -> None:
    """to_spec для MulticastRoutesProcessor совместим с YAML round-trip."""
    proc = MulticastRoutesProcessor(
        ["a", "b", "c"], strategy="first_success", on_error="fail", timeout=15.0
    )
    assert proc.to_spec() == {
        "multicast_routes": {
            "route_ids": ["a", "b", "c"],
            "strategy": "first_success",
            "on_error": "fail",
            "timeout": 15.0,
        }
    }
