"""ADR-0430 — caller-aware namespace для capability-проверок.

Контекст
--------
Фасады ядра создаются с платформенным namespace'ом (``system``/``core``), и
проверка capability шла под baseline'ом платформы: декларации роута
(``route.toml`` → ``storage.*``/``db.*``/``cache.*``) на неё не влияли.

Проверяется здесь:

* привязанный namespace вызывающего используется вместо платформенного;
* без привязки (роут без деклараций) поведение прежнее — платформенный
  namespace (регрессия не ломает существующие роуты);
* gate умеет отвечать «есть ли декларации у плагина» (``has_plugin``);
* DSL-движок привязывает namespace только для роутов с декларациями.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.security.capabilities.caller import (
    bind_caller_namespace,
    current_caller_namespace,
    effective_plugin,
    reset_caller_namespace,
)

pytestmark = pytest.mark.unit


class TestCallerNamespace:
    """ContextVar namespace'а вызывающего."""

    def test_default_is_none(self) -> None:
        """Без привязки namespace'а нет."""
        assert current_caller_namespace() is None
        assert effective_plugin("system") == "system"

    def test_bind_and_reset(self) -> None:
        """Привязка/снятие namespace'а вызывающего."""
        token = bind_caller_namespace("orders.get")
        try:
            assert current_caller_namespace() == "orders.get"
            assert effective_plugin("system") == "orders.get"
        finally:
            reset_caller_namespace(token)
        assert current_caller_namespace() is None
        assert effective_plugin("system") == "system"


class TestFacadeUsesCallerNamespace:
    """Фасад проверяет capability под namespace'ом вызывающего."""

    def test_storage_facade_uses_caller_namespace(self) -> None:
        """``StorageFacade`` передаёт в gate namespace вызывающего."""
        from src.backend.services.storage.facade import StorageFacade

        seen: list[str] = []

        def _check(plugin: str, capability: str, scope: str | None) -> None:
            seen.append(plugin)

        class _Storage:
            async def exists(self, key: str) -> bool:
                return False

            async def download(self, key: str) -> bytes:
                return b""

            async def upload(self, key: str, data: bytes) -> str:
                return key

        facade = StorageFacade(
            _Storage(),  # type: ignore[arg-type]
            capability_check=_check,
            plugin="system",
        )

        token = bind_caller_namespace("orders.get")
        try:
            import asyncio

            asyncio.run(facade.exists("bucket/key"))
        finally:
            reset_caller_namespace(token)

        assert seen == ["orders.get"], seen

    def test_storage_facade_without_caller_uses_platform(self) -> None:
        """Без привязки — платформенный namespace (прежнее поведение)."""
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

        import asyncio

        asyncio.run(facade.exists("bucket/key"))
        assert seen == ["system"], seen


class TestGateHasPlugin:
    """``CapabilityGate.has_plugin`` — есть ли декларации у namespace'а."""

    def test_has_plugin_reflects_declarations(self) -> None:
        """Декларированный плагин виден, недекларированный — нет."""
        from src.backend.core.security.capabilities.gate import CapabilityGate
        from src.backend.core.security.capabilities import (
            CapabilityRef,
            build_default_vocabulary,
        )

        gate = CapabilityGate(vocabulary=build_default_vocabulary())
        gate.declare("orders.get", [CapabilityRef(name="storage.read", scope="bucket/*")])

        assert gate.has_plugin("orders.get") is True
        assert gate.has_plugin("orders.unknown") is False


class TestEngineBindsNamespace:
    """DSL-движок привязывает namespace только для роутов с декларациями."""

    def test_namespace_bound_only_for_declared_routes(self) -> None:
        """Роут без деклараций → namespace не привязывается (регрессия-safe)."""
        from src.backend.dsl.engine.execution_engine import ExecutionEngine
        from src.backend.dsl.engine.pipeline import Pipeline

        pipeline = Pipeline(route_id="orders.get", processors=[])
        assert ExecutionEngine._caller_namespace(pipeline) is None

    def test_namespace_bound_for_declared_route(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Роут с декларациями → namespace вызывающего = route_id."""
        from src.backend.core.security.capabilities.gate import CapabilityGate
        from src.backend.core.security.capabilities import (
            CapabilityRef,
            build_default_vocabulary,
        )
        from src.backend.dsl.engine.execution_engine import ExecutionEngine
        from src.backend.dsl.engine.pipeline import Pipeline

        gate = CapabilityGate(vocabulary=build_default_vocabulary())
        gate.declare("orders.get", [CapabilityRef(name="storage.read", scope="bucket/*")])
        monkeypatch.setattr(
            "src.backend.core.security.capabilities.gate.get_capability_gate",
            lambda: gate,
        )

        pipeline = Pipeline(route_id="orders.get", processors=[])
        assert ExecutionEngine._caller_namespace(pipeline) == "orders.get"

    def test_execute_unbinds_namespace(self) -> None:
        """После исполнения маршрута привязка снимается."""
        from src.backend.dsl.engine.execution_engine import ExecutionEngine
        from src.backend.dsl.engine.pipeline import Pipeline

        engine = ExecutionEngine(validate_before_execute=False)
        pipeline = Pipeline(route_id="orders.get", processors=[])

        import asyncio

        asyncio.run(engine.execute(pipeline))
        assert current_caller_namespace() is None


def test_effective_plugin_prefers_caller() -> None:
    """``effective_plugin`` — caller приоритетнее платформенного fallback."""
    token = bind_caller_namespace("my.route")
    try:
        assert effective_plugin("core") == "my.route"
    finally:
        reset_caller_namespace(token)
    assert effective_plugin("core") == "core"


def test_caller_namespace_is_context_local() -> None:
    """Изменения привязки в задаче не протекают в родителя.

    Новая asyncio-задача **наследует** контекст (копию), поэтому дочерняя
    задача видит текущий namespace; но сброс привязки в родителе не влияет
    на копию дочерней задачи и vice versa.
    """
    import asyncio

    async def _inner() -> Any:
        return current_caller_namespace()

    async def _main() -> tuple[Any, Any]:
        token = bind_caller_namespace("outer")
        try:
            inner = await asyncio.create_task(_inner())
        finally:
            reset_caller_namespace(token)
        return inner, current_caller_namespace()

    inner, outer = asyncio.run(_main())
    assert inner == "outer", "дочерняя задача наследует контекст"
    assert outer is None, "после reset в родителе привязки нет"
