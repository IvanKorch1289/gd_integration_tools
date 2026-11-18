"""ADR-0430 — caller-namespace в **последовательном** пути DSL-движка.

До фикса ``bind_caller_namespace(...)`` вызывался только в
``ExecutionEngine.execute_parallel``. В последовательном пути (исполнение
одного процессора за другим) namespace не привязывался → capability-проверки
фасадов (``StorageFacade`` / ``UnifiedCacheFacade`` /
``ExternalDatabaseFacade`` / ``OutboundHttpClient``) шли под платформенным
namespace'ом (``system`` / ``core``), и декларации роута
(``[[route.capabilities]]`` → ``storage.*`` / ``db.*`` / ``cache.*`` /
``net.outbound``) на них не влияли.

Проверяется:
* роут с декларациями → namespace вызывающего = ``route_id`` на время шага;
* роут без деклараций → namespace **не** привязывается (fail-safe:
  проверка идёт под платформенным namespace'ом, прежнее поведение);
* привязка снимается после исполнения — в т.ч. после падения шага;
* фасад под route-id проверяет capability именно роута.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.security.capabilities import (
    CapabilityRef,
    build_default_vocabulary,
)
from src.backend.core.security.capabilities.caller import current_caller_namespace
from src.backend.core.security.capabilities.gate import CapabilityGate
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.execution_engine import ExecutionEngine
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor

pytestmark = pytest.mark.unit


class _NamespaceSpyProcessor(BaseProcessor):
    """Записывает namespace вызывающего, видимый внутри шага."""

    def __init__(self, seen: list[str | None]) -> None:
        super().__init__(name="namespace-spy")
        self._seen = seen

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        self._seen.append(current_caller_namespace())


class _FailingProcessor(BaseProcessor):
    """Падающий шаг — проверяем снятие привязки в ``finally``."""

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        raise RuntimeError("step boom")


def _gate_with_declarations(*names: str) -> CapabilityGate:
    """Гейт с декларациями для роута ``orders.get``."""
    gate = CapabilityGate(vocabulary=build_default_vocabulary())
    gate.declare(
        "orders.get", [CapabilityRef(name=name, scope="bucket/*") for name in names]
    )
    return gate


@pytest.fixture
def declared_gate(monkeypatch: pytest.MonkeyPatch) -> CapabilityGate:
    """Подменяет process-wide гейт на гейт с декларациями ``orders.get``."""
    gate = _gate_with_declarations("storage.read")
    monkeypatch.setattr(
        "src.backend.core.security.capabilities.gate.get_capability_gate", lambda: gate
    )
    return gate


class TestSequentialCallerNamespace:
    """Последовательный путь — симметрично параллельному."""

    async def test_namespace_bound_for_declared_route(
        self, declared_gate: CapabilityGate
    ) -> None:
        """Роут с декларациями → namespace вызывающего = route_id."""
        seen: list[str | None] = []
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(
            route_id="orders.get", processors=[_NamespaceSpyProcessor(seen)]
        )

        await engine.execute(pipeline)

        assert seen == ["orders.get"], seen

    async def test_namespace_not_bound_without_declarations(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Роут без деклараций → namespace не привязывается (fail-safe)."""
        gate = CapabilityGate(vocabulary=build_default_vocabulary())
        monkeypatch.setattr(
            "src.backend.core.security.capabilities.gate.get_capability_gate",
            lambda: gate,
        )

        seen: list[str | None] = []
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(
            route_id="orders.get", processors=[_NamespaceSpyProcessor(seen)]
        )

        await engine.execute(pipeline)

        assert seen == [None], seen

    async def test_namespace_unbound_after_execution(
        self, declared_gate: CapabilityGate
    ) -> None:
        """После исполнения маршрута привязка снята."""
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(route_id="orders.get", processors=[])

        await engine.execute(pipeline)

        assert current_caller_namespace() is None

    async def test_namespace_unbound_after_step_failure(
        self, declared_gate: CapabilityGate
    ) -> None:
        """После падения шага привязка тоже снята (finally)."""
        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(
            route_id="orders.get", processors=[_FailingProcessor(name="boom")]
        )

        exchange = await engine.execute(pipeline)

        assert exchange.status.value == "failed"
        assert current_caller_namespace() is None

    async def test_facade_checks_route_namespace(
        self, declared_gate: CapabilityGate
    ) -> None:
        """Фасад под route-id проверяет capability роута, а не платформы."""
        from src.backend.services.storage.facade import StorageFacade

        seen: list[str] = []

        class _Storage:
            async def exists(self, key: str) -> bool:
                return False

        facade = StorageFacade(
            _Storage(),  # type: ignore[arg-type]
            capability_check=lambda plugin, capability, scope: seen.append(plugin),
            plugin="system",
        )

        class _FacadeProcessor(BaseProcessor):
            async def process(self, exchange: Exchange[Any], context: Any) -> None:
                await facade.exists("bucket/key")

        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(
            route_id="orders.get", processors=[_FacadeProcessor(name="facade")]
        )

        await engine.execute(pipeline)

        assert seen == ["orders.get"], (
            "фасад проверил capability под платформенным namespace'ом — "
            "декларации роута не влияют на проверку (ADR-0430)"
        )


class TestPlatformBaselineSafety:
    """Инвариант: привязка namespace не может превратить GRANT в DENY.

    Фасады, использующие ``effective_plugin(...)``, проверяют capability из
    :data:`RESOURCE_SCOPED_CAPABILITIES` (``storage.*`` / ``cache.*`` /
    ``db.*`` / ``net.outbound``). Ни одна из них не объявлена в
    платформенных namespace'ах ``core`` / ``system`` / ``ai-agent``
    (ADR-0416: ресурсные capability объявляет владелец ресурса).

    Следствие: перенос проверки с платформенного namespace'а на namespace
    роута даёт только ``DENY → DENY`` или ``DENY → GRANT`` — уже работавшая
    проверка (``GRANT``) в ``DENY`` не превращается, то есть ни один
    существующий роут не ломается. Если в baseline платформы появится
    ресурсная capability — тест упадёт и потребует повторного аудита.
    """

    #: Capability, которые проверяют фасады через ``effective_plugin(...)``.
    FACADE_CAPABILITIES = (
        "storage.read",
        "storage.write",
        "storage.presign",
        "cache.read",
        "cache.write",
        "db.read",
        "db.write",
        "db.execute_procedure",
        "net.outbound",
    )

    def test_platform_namespaces_declare_no_resource_capabilities(self) -> None:
        """В платформенных namespace'ах нет ресурсных capability."""
        from src.backend.core.security.capabilities.gate import get_capability_gate

        gate = get_capability_gate()
        offenders: list[str] = []
        for namespace in ("core", "system", "ai-agent"):
            declared = gate._declarations.get(namespace, {})
            for capability in self.FACADE_CAPABILITIES:
                if capability in declared:
                    offenders.append(f"{namespace}.{capability}")

        assert not offenders, (
            "платформенный baseline объявляет ресурсную capability "
            f"{offenders} → привязка caller-namespace может превратить "
            "GRANT в DENY (нужен повторный аудит роутов, ADR-0430)"
        )
