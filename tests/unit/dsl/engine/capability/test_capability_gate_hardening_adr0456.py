"""ADR-0456 (hardening) — регрессы engine-wide capability-гейта DSL-движка.

Что закрывают тесты
--------------------
* **Маркер проверки привязан к exchange.** До hardening'а маркер
  ``capability_verified`` жил на экземпляре процессора и не сбрасывался
  между запросами: один и тот же экземпляр (роуты живут в process-wide
  registry) мог «помнить» успешную проверку чужого exchange — внутренний
  ``auth_check()`` нового запроса пропускался.
* **Вложенные шаги под гейтом.** Шаги, которые вызывались напрямую
  (``proc.process(...)``), а не через :func:`run_sub_processors`, обходили
  движковый гейт: декларация capability оставалась декоративной.
* **Параллельный путь.** После отказа capability-гейта остальные шаги
  параллельной пачки не должны выполняться.
* **Trace.** Длительность упавшего шага — время шага, а не всего pipeline.
* **Retry.** Отказ capability-гейта не ретраится (решение детерминировано).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.core.security.capabilities.gate import get_capability_gate
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.dsl.engine.capability_guard import enforce_step_capability
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processor_pool import ProcessorPool
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow.flow import (
    RetryProcessor,
    TryCatchProcessor,
)
from src.backend.dsl.engine.processors.control_flow.saga import SagaProcessor, SagaStep
from src.backend.dsl.engine.processors.eip.flow_control.oncompletion import (
    OnCompletionProcessor,
)
from src.backend.dsl.engine.processors.eip.resilience import FallbackChainProcessor

pytestmark = pytest.mark.unit

#: Реальный capability-гейт (иначе autouse-фикстура ``tests/unit/dsl/conftest.py``
#: подменяет ``BaseProcessor.auth_check`` и проверка была бы вакуумной).
REAL_CAPABILITY_GATE = True

_CAPABILITY = "audit.write"


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
    """Шаг с capability-декларацией и scope ``audit:step``."""

    required_capability = _CAPABILITY
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
    """Шаг, который сам вызывает ``auth_check`` (opt-in-пагтерн)."""

    def __init__(self) -> None:
        super().__init__()
        self.name = "self-checking-step"

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        """Проверяет capability сам."""
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


def _exchange(route_id: str) -> Exchange[Any]:
    """Создать Exchange с привязанным route_id."""
    exchange = Exchange(in_message=Message(body={}))
    exchange.meta.route_id = route_id
    return exchange


# ── маркер проверки: привязка к exchange ───────────────────────────────────


@pytest.mark.asyncio
async def test_marker_does_not_leak_between_exchanges(gate: Any) -> None:
    """Успешная проверка одного exchange не отменяет проверку другого.

    Экземпляры процессоров переиспользуются между запросами (process-wide
    registry роутов) — «помнить» проверку чужого exchange нельзя.
    """
    gate.declare("r_ok", [CapabilityRef(name=_CAPABILITY, scope="audit:*")])
    step = _SelfCheckingStep()

    allowed_exchange = _exchange("r_ok")
    denied_exchange = _exchange("r_unknown")

    assert await enforce_step_capability(step, allowed_exchange, ExecutionContext())
    # Новый exchange без декларации → проверка обязана быть выполнена again.
    assert await step.auth_check(denied_exchange, action="write") is False
    assert denied_exchange.status == ExchangeStatus.failed


@pytest.mark.asyncio
async def test_engine_uses_processor_capability_action(
    gate: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Движок запрашивает то же действие, что и процессор (1 проверка на шаг).

    Если движок спрашивает ``execute``, а процессор — ``write``, внутренний
    ``auth_check()`` не совпадает с проверкой движка → гейт опрашивается
    дважды и audit пишет неверное действие.
    """
    gate.declare("r_action", [CapabilityRef(name=_CAPABILITY, scope="audit:*")])
    calls: list[tuple[str, str, str | None]] = []
    original = gate.check

    def _counting_check(
        plugin: str, capability: str, requested_scope: str | None
    ) -> None:
        calls.append((plugin, capability, requested_scope))
        original(plugin, capability, requested_scope)

    monkeypatch.setattr(gate, "check", _counting_check)

    step = _SelfCheckingStep()
    exchange = _exchange("r_action")
    assert await enforce_step_capability(step, exchange, ExecutionContext())
    # Внутренняя проверка процессора — идемпотентна (совпадающий запрос).
    assert await step.auth_check(exchange, action="write") is True

    assert len(calls) == 1, f"ожидался один вызов гейта, получено: {calls}"


# ── вложенные шаги: обходы гейта ───────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("factory", "label"),
    [
        (lambda step: TryCatchProcessor([], finally_processors=[step]), "try/finally"),
        (lambda step: RetryProcessor([step], delay_seconds=0.0), "retry"),
        (lambda step: FallbackChainProcessor([step]), "fallback_chain"),
        (lambda step: SagaProcessor([SagaStep(forward=step)]), "saga"),
        (lambda step: OnCompletionProcessor([step]), "on_completion"),
    ],
)
async def test_nested_step_is_capability_checked(
    gate: Any, factory: Any, label: str
) -> None:
    """Вложенный шаг с capability декларацией — тоже под гейтом.

    Вложенные шаги выполнялись напрямую (``proc.process(...)``) и обходили
    движковый enforcement — декларация оставалась декоративной.
    """
    step = _CapabilityStep()
    container = factory(step)
    exchange = _exchange("r_nested_unknown")

    await container.process(exchange, ExecutionContext())

    assert step.calls == 0, f"{label}: отклонённый вложенный шаг не должен выполняться"
    assert exchange.status == ExchangeStatus.failed, f"{label}: ожидался failed"


@pytest.mark.asyncio
async def test_retry_does_not_retry_capability_denial(gate: Any) -> None:
    """Отказ capability-гейта не ретраится (решение детерминировано)."""
    attempts: list[int] = []

    class _CountingStep(_CapabilityStep):
        async def process(self, exchange: Exchange[Any], context: Any) -> None:
            """Считает попытки (шаг не должен выполниться)."""
            del context
            attempts.append(1)
            self.calls += 1

    step = _CountingStep()
    retry = RetryProcessor([step], max_attempts=3, delay_seconds=0.0)
    exchange = _exchange("r_retry_unknown")

    await retry.process(exchange, ExecutionContext())

    assert step.calls == 0
    assert attempts == []
    assert exchange.status == ExchangeStatus.failed


# ── параллельный путь ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parallel_siblings_stopped_after_denial(gate: Any) -> None:
    """После отказа гейта остальные шаги параллельной пачки не выполняются."""
    denied = _CapabilityStep()
    sibling = _PlainStep()
    exchange = _exchange("r_parallel_unknown")

    pool = ProcessorPool(max_workers=2)
    try:
        trace = await pool.execute_parallel(
            [denied, sibling], exchange, ExecutionContext()
        )
    finally:
        await pool.shutdown()

    assert denied.calls == 0
    assert sibling.calls == 0, "после отказа capability-гейта шаг выполняться не должен"
    statuses = {entry["processor"]: entry["status"] for entry in trace}
    assert statuses["capability-step"] == "denied"
    assert statuses["plain-step"] == "stopped"


# ── trace ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_step_duration_is_step_duration() -> None:
    """Длительность упавшего шага — время шага, а не всего pipeline."""

    class _SlowStep(BaseProcessor):
        async def process(self, exchange: Exchange[Any], context: Any) -> None:
            """Затягивает шаг на 60 мс."""
            del context
            await asyncio.sleep(0.06)
            exchange.set_property("slow", True)

    class _FailingStep(BaseProcessor):
        async def process(self, exchange: Exchange[Any], context: Any) -> None:
            """Падает с исключением."""
            del context
            raise RuntimeError("boom")

    pipeline = Pipeline(
        route_id="r_trace",
        source="internal:test",
        processors=[_SlowStep(), _FailingStep()],
        tenant_aware=False,
    )
    engine = ExecutionEngine(validate_before_execute=False)

    exchange = await engine.execute(pipeline)

    trace = list(exchange.get_property("_trace") or [])
    assert len(trace) == 2
    # Второй шаг упал почти мгновенно — его длительность не включает
    # 60 мс первого шага.
    assert trace[1]["duration_ms"] < 50.0, (
        "duration_ms упавшего шага не должен включать время предыдущих шагов: "
        f"{trace[1]['duration_ms']}"
    )
    assert trace[1]["status"] == "error"
