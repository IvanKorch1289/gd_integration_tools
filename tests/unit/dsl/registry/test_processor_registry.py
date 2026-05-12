"""Unit-тесты :class:`ProcessorRegistry` — Stage 3, V15 Sprint 1."""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import (
    ProcessorConflictError,
    ProcessorNotFoundError,
    ProcessorRegistry,
    ProcessorSpec,
    get_processor_registry,
    processor,
)


class _DummyProcessor(BaseProcessor):
    """Лёгкий процессор-заглушка для тестов."""

    async def process(self, exchange):  # type: ignore[no-untyped-def]
        return exchange


@pytest.fixture
def fresh_registry() -> ProcessorRegistry:
    """Изолированный реестр (не общесистемный singleton)."""

    return ProcessorRegistry()


class TestProcessorRegistryBasics:
    def test_register_and_get_by_fqn(self, fresh_registry: ProcessorRegistry) -> None:
        spec = ProcessorSpec(
            name="dummy", namespace="test", cls=_DummyProcessor
        )
        fresh_registry.register(spec)
        assert fresh_registry.get("test:dummy") is spec
        assert "test:dummy" in fresh_registry
        assert len(fresh_registry) == 1

    def test_get_unknown_raises(self, fresh_registry: ProcessorRegistry) -> None:
        with pytest.raises(ProcessorNotFoundError):
            fresh_registry.get("missing:processor")

    def test_get_by_short_prefers_core(
        self, fresh_registry: ProcessorRegistry
    ) -> None:
        core = ProcessorSpec(name="dummy", namespace="core", cls=_DummyProcessor)
        plugin = ProcessorSpec(name="dummy", namespace="plug", cls=_DummyProcessor)
        fresh_registry.register(core)
        fresh_registry.register(plugin)

        # default prefer_namespace="core"
        assert fresh_registry.get_by_short("dummy") is core
        assert (
            fresh_registry.get_by_short("dummy", prefer_namespace="plug") is plugin
        )

    def test_list_by_namespace(self, fresh_registry: ProcessorRegistry) -> None:
        a = ProcessorSpec(name="x", namespace="ns1", cls=_DummyProcessor)
        b = ProcessorSpec(name="y", namespace="ns1", cls=_DummyProcessor)
        c = ProcessorSpec(name="z", namespace="ns2", cls=_DummyProcessor)
        for s in (a, b, c):
            fresh_registry.register(s)

        ns1 = fresh_registry.list_by_namespace("ns1")
        assert {s.name for s in ns1} == {"x", "y"}


class TestProcessorRegistryConflict:
    def test_duplicate_fqn_without_replaces_raises(
        self, fresh_registry: ProcessorRegistry
    ) -> None:
        a = ProcessorSpec(name="dup", namespace="core", cls=_DummyProcessor)
        b = ProcessorSpec(name="dup", namespace="core", cls=_DummyProcessor)
        fresh_registry.register(a)
        with pytest.raises(ProcessorConflictError):
            fresh_registry.register(b)

    def test_replaces_overrides_existing(
        self, fresh_registry: ProcessorRegistry
    ) -> None:
        original = ProcessorSpec(
            name="http", namespace="core", cls=_DummyProcessor
        )
        fresh_registry.register(original)

        override = ProcessorSpec(
            name="http",
            namespace="core",
            cls=_DummyProcessor,
            replaces="core:http",
            meta={"override_by": "test"},
        )
        fresh_registry.register(override)

        assert fresh_registry.get("core:http") is override
        assert fresh_registry.get("core:http").meta["override_by"] == "test"

    def test_replaces_unknown_raises(
        self, fresh_registry: ProcessorRegistry
    ) -> None:
        spec = ProcessorSpec(
            name="x", namespace="plug", cls=_DummyProcessor, replaces="core:nope"
        )
        with pytest.raises(ProcessorNotFoundError):
            fresh_registry.register(spec)


class TestProcessorRegistryUnregister:
    def test_unregister_removes_entry(
        self, fresh_registry: ProcessorRegistry
    ) -> None:
        spec = ProcessorSpec(name="x", namespace="ns", cls=_DummyProcessor)
        fresh_registry.register(spec)
        assert "ns:x" in fresh_registry
        fresh_registry.unregister("ns:x")
        assert "ns:x" not in fresh_registry

    def test_unregister_unknown_is_noop(
        self, fresh_registry: ProcessorRegistry
    ) -> None:
        # silent for hot-reload sanity
        fresh_registry.unregister("missing:thing")


class TestProcessorDecorator:
    def teardown_method(self) -> None:
        """Очистка global singleton'а после каждого теста."""

        registry = get_processor_registry()
        for fqn in ("test_decor:my_proc", "test_decor:override_test"):
            registry.unregister(fqn)

    def test_decorator_registers_in_global_singleton(self) -> None:
        @processor("my_proc", namespace="test_decor")
        class _MyProc(BaseProcessor):
            async def process(self, exchange):  # type: ignore[no-untyped-def]
                return exchange

        registry = get_processor_registry()
        assert "test_decor:my_proc" in registry
        spec = registry.get("test_decor:my_proc")
        assert spec.cls is _MyProc
        # __processor_spec__ atttached to class
        assert _MyProc.__processor_spec__ is spec  # type: ignore[attr-defined]

    def test_decorator_with_schemas_and_capabilities(self) -> None:
        spec_schema = {"type": "object", "properties": {"target": {"type": "string"}}}
        output_schema = {"type": "object"}

        @processor(
            "override_test",
            namespace="test_decor",
            spec_schema=spec_schema,
            output_schema=output_schema,
            capabilities=("net.outbound.example.com:external",),
            meta={"tier": 1},
        )
        class _T(BaseProcessor):
            async def process(self, exchange):  # type: ignore[no-untyped-def]
                return exchange

        registry = get_processor_registry()
        spec = registry.get("test_decor:override_test")
        assert spec.spec_schema == spec_schema
        assert spec.output_schema == output_schema
        assert spec.capabilities == ("net.outbound.example.com:external",)
        assert spec.meta == {"tier": 1}
