"""ADR-0456 — engine-wide enforcement capability в DSL-движке (ADR-0449, поз. №1).

Контекст
--------
Capability-гейт вызывался **самим процессором** (opt-in):
``BaseProcessor.auth_check()`` внутри ``process()``. Шаг с
capability-декларацией другого процессора выполнялся **без проверки** —
декларация оставалась декоративной. Общего пути исполнения шага не было.

Проверяется здесь:

* шаг с объявленной capability и **без** декларации в манифесте роута →
  движок отклоняет шаг (шаг **не выполняется**, exchange → ``failed``);
* шаг с объявленной capability и **с** декларацией → шаг выполняется;
* scope проверяется: декларация другого scope не покрывает запрос;
* шаг **без** capability-декларации → поведение не изменилось;
* проверка идемпотентна: внутренний ``auth_check()`` процессора не
  дублирует проверку движка (один вызов гейта на шаг).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.security.capabilities.gate import get_capability_gate
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor

pytestmark = pytest.mark.unit

#: Реальный capability-гейт: без этой подмены autouse-фикстура
#: ``tests/unit/dsl/conftest.py`` подменяет ``BaseProcessor.auth_check`` на
#: «всегда разрешено» (ADR-0393) — и проверка гейта была бы вакуумной.
REAL_CAPABILITY_GATE = True


@pytest.fixture(autouse=True)
def _gate_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Capability-гейт включён (ADR-0366), baseline ядра выключен."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "dsl_capability_gate_enabled", True)
    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", False)


@pytest.fixture
def gate() -> Any:
    """Изолированный process-wide singleton capability-гейта."""
    get_capability_gate.cache_clear()
    instance = get_capability_gate()
    yield instance
    get_capability_gate.cache_clear()


class _CapabilityStep(BaseProcessor):
    """Шаг с объявленной capability, который **сам** гейт не проверяет."""

    required_capability = "audit.write"
    # ADR-0456: действие capability-запроса обязано совпадать с тем,
    # которое просит сам процессор (``auth_check(action=...)``) — иначе
    # движок проверяет другой запрос и внутренняя проверка не идемпотентна.
    capability_action = "write"

    def __init__(self) -> None:
        super().__init__(name="capability-step")
        self.calls = 0

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope запроса — ``audit:<action>``-стиля (ADR-0454)."""
        del exchange
        return "audit:step"

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Отмечает факт выполнения шага."""
        del context
        self.calls += 1
        exchange.set_property("step_executed", True)


class _SelfCheckingStep(_CapabilityStep):
    """Шаг, который сам вызывает ``auth_check`` (как БД-/RPA-процессоры)."""

    def __init__(self) -> None:
        super().__init__()
        self.name = "self-checking-step"

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Проверяет capability сам (opt-in-паттерн до ADR-0456)."""
        if not await self.auth_check(exchange, action="write"):
            return
        self.calls += 1
        exchange.set_property("step_executed", True)


class _PlainStep(BaseProcessor):
    """Шаг без capability-декларации."""

    def __init__(self) -> None:
        super().__init__(name="plain-step")
        self.calls = 0

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Отмечает факт выполнения шага."""
        del context
        self.calls += 1
        exchange.set_property("step_executed", True)


async def _run(
    processor: BaseProcessor, route_id: str
) -> tuple[Exchange[Any], dict[str, Any]]:
    """Прогоняет pipeline из одного шага.

    Args:
        processor: Шаг pipeline.
        route_id: Имя роута (namespace capability-гейта).

    Returns:
        Кортеж ``(exchange, trace)`` — результат выполнения и trace-шаг.

    """
    pipeline = Pipeline(
        route_id=route_id,
        source="internal:test",
        processors=[processor],
        tenant_aware=False,
    )
    engine = ExecutionEngine(validate_before_execute=False)
    exchange = await engine.execute(pipeline)
    trace = list(exchange.get_property("_trace") or [])
    return exchange, dict(trace[0]) if trace else {}


@pytest.mark.asyncio
async def test_step_denied_without_declaration(gate: Any) -> None:
    """Шаг с capability без декларации в манифесте → отказ, шаг не выполнен."""
    step = _CapabilityStep()

    exchange, trace = await _run(step, "r_engine_no_decl")

    assert exchange.status.value == "failed", (
        "шаг с объявленной capability без декларации должен быть отклонён, "
        f"получено status={exchange.status.value!r}"
    )
    assert "audit.write" in (exchange.error or ""), (
        f"в ошибке должно быть имя capability, получено: {exchange.error!r}"
    )
    assert step.calls == 0, "отклонённый шаг не должен выполняться"
    assert exchange.get_property("step_executed") is None
    assert trace.get("status") == "denied"


@pytest.mark.asyncio
async def test_step_allowed_with_declaration(gate: Any) -> None:
    """Шаг с capability и декларацией (scope ``audit:*``) → выполняется."""
    gate.declare("r_engine_ok", [CapabilityRef(name="audit.write", scope="audit:*")])
    step = _CapabilityStep()

    exchange, trace = await _run(step, "r_engine_ok")

    assert exchange.status.value != "failed", (
        "шаг с объявленной capability должен выполняться, "
        f"получено status={exchange.status.value!r} error={exchange.error!r}"
    )
    assert step.calls == 1
    assert exchange.get_property("step_executed") is True
    assert trace.get("status") == "ok"


@pytest.mark.asyncio
async def test_step_denied_on_scope_mismatch(gate: Any) -> None:
    """Декларация с другим scope не покрывает запрос шага."""
    gate.declare(
        "r_engine_scope", [CapabilityRef(name="audit.write", scope="audit:other")]
    )
    step = _CapabilityStep()

    exchange, _ = await _run(step, "r_engine_scope")

    assert exchange.status.value == "failed"
    assert step.calls == 0


@pytest.mark.asyncio
async def test_step_without_capability_unchanged(gate: Any) -> None:
    """Шаг без capability-декларации → поведение не изменилось."""
    step = _PlainStep()

    exchange, trace = await _run(step, "r_engine_plain")

    assert exchange.status.value == "completed"
    assert step.calls == 1
    assert exchange.get_property("step_executed") is True
    assert trace.get("status") == "ok"


@pytest.mark.asyncio
async def test_gate_consulted_once_per_step(
    gate: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Проверка идемпотентна: гейт спрашивается один раз на шаг.

    Процессор, который сам вызывает ``auth_check()``, не должен
    порождать вторую проверку (и второе audit-событие).
    """
    gate.declare("r_engine_once", [CapabilityRef(name="audit.write", scope="audit:*")])
    calls: list[tuple[str, str, str | None]] = []
    original = gate.check

    def _counting_check(
        plugin: str, capability: str, requested_scope: str | None
    ) -> None:
        calls.append((plugin, capability, requested_scope))
        original(plugin, capability, requested_scope)

    monkeypatch.setattr(gate, "check", _counting_check)
    step = _SelfCheckingStep()

    exchange, _ = await _run(step, "r_engine_once")

    assert exchange.status.value != "failed", exchange.error
    assert step.calls == 1
    assert len(calls) == 1, f"ожидался один вызов гейта, получено: {calls}"


@pytest.mark.asyncio
async def test_denied_step_stops_pipeline(gate: Any) -> None:
    """Отклонённый шаг останавливает pipeline — следующие шаги не выполняются."""
    gate.declare(
        "r_engine_chain_ok", [CapabilityRef(name="audit.write", scope="audit:*")]
    )
    denied = _CapabilityStep()
    following = _PlainStep()
    pipeline = Pipeline(
        route_id="r_engine_chain",
        source="internal:test",
        processors=[denied, following],
        tenant_aware=False,
    )
    engine = ExecutionEngine(validate_before_execute=False)

    exchange = await engine.execute(pipeline)

    assert exchange.status.value == "failed"
    assert denied.calls == 0
    assert following.calls == 0, "после отказа шаги выполняться не должны"


@pytest.mark.asyncio
async def test_nested_step_checked_by_engine(gate: Any) -> None:
    """Вложенный шаг (``run_sub_processors``) — тоже под capability-гейтом."""
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.processors.base import run_sub_processors

    nested = _CapabilityStep()
    exchange = Exchange(in_message=Message(body={}))
    exchange.meta.route_id = "r_engine_nested"

    await run_sub_processors([nested], exchange, ExecutionContext())

    assert exchange.status.value == "failed"
    assert nested.calls == 0
