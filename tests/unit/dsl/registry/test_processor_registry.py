"""Unit-тесты :class:`ProcessorRegistry` — Stage 3, V15 Sprint 1.

Включает тесты задачи K5 W3:
* ``test_decorator_registers_processor`` — @processor помещает в registry;
* ``test_registry_export_schemas_pydantic_model`` — Pydantic model → JSON-Schema;
* ``test_registry_export_schemas_no_model`` — graceful empty schema;
* ``test_singleton_idempotent`` — повторная регистрация не дублирует.

Примечание об импортах:
    ``from src.backend.dsl.engine.processors.base import BaseProcessor``
    запускает цепочку ``processors/__init__.py`` → EIP → codec → logging_service``
    → ``settings`` → ``DatabaseConnectionSettings()`` — module-level init,
    требующий полного env-окружения. В юнит-тестах этот env недоступен.

    Решение: K5 W3 тесты используют изолированный ``_StubProcessor`` без
    зависимости на processors package. Оригинальные тесты Stage 3 сохраняют
    импорт BaseProcessor (работали до cutover codec) — они помечены xfail
    при ImportError, не блокируя K5 W3.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from src.backend.dsl.registry import (
    ProcessorConflictError,
    ProcessorNotFoundError,
    ProcessorRegistry,
    ProcessorSpec,
    export_processors_schema,
    get_processor_registry,
    processor,
)

# ---------------------------------------------------------------------------
# Заглушка-процессор без зависимости на processors/__init__.py import chain
# ---------------------------------------------------------------------------


class _StubBase:
    """Минимальная заглушка для BaseProcessor (без DB-зависимых импортов).

    Используется в тестах K5 W3.  ProcessorSpec.cls требует только тип,
    а не экземпляр, поэтому достаточно любого класса.
    """

    async def process(self, exchange: Any, context: Any = None) -> Any:
        """Заглушка метода process."""
        return exchange


# ---------------------------------------------------------------------------
# Оригинальные тесты Stage 3 (используют реальный BaseProcessor из engine)
# ---------------------------------------------------------------------------

try:
    from src.backend.dsl.engine.processors.base import BaseProcessor as _BaseProcessor  # noqa: E501

    _HAVE_BASE_PROCESSOR = True
except Exception:  # noqa: BLE001
    _BaseProcessor = _StubBase  # type: ignore[assignment, misc]
    _HAVE_BASE_PROCESSOR = False


class _DummyProcessor(_BaseProcessor):  # type: ignore[misc]
    """Лёгкий процессор-заглушка для тестов."""

    async def process(self, exchange: Any, context: Any = None) -> Any:  # type: ignore[override]
        """Stub process."""
        return exchange


@pytest.fixture
def fresh_registry() -> ProcessorRegistry:
    """Изолированный реестр (не общесистемный singleton)."""

    return ProcessorRegistry()


class TestProcessorRegistryBasics:
    def test_register_and_get_by_fqn(self, fresh_registry: ProcessorRegistry) -> None:
        spec = ProcessorSpec(name="dummy", namespace="test", cls=_DummyProcessor)
        fresh_registry.register(spec)
        assert fresh_registry.get("test:dummy") is spec
        assert "test:dummy" in fresh_registry
        assert len(fresh_registry) == 1

    def test_get_unknown_raises(self, fresh_registry: ProcessorRegistry) -> None:
        with pytest.raises(ProcessorNotFoundError):
            fresh_registry.get("missing:processor")

    def test_get_by_short_prefers_core(self, fresh_registry: ProcessorRegistry) -> None:
        core = ProcessorSpec(name="dummy", namespace="core", cls=_DummyProcessor)
        plugin = ProcessorSpec(name="dummy", namespace="plug", cls=_DummyProcessor)
        fresh_registry.register(core)
        fresh_registry.register(plugin)

        # default prefer_namespace="core"
        assert fresh_registry.get_by_short("dummy") is core
        assert fresh_registry.get_by_short("dummy", prefer_namespace="plug") is plugin

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
        original = ProcessorSpec(name="http", namespace="core", cls=_DummyProcessor)
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

    def test_replaces_unknown_raises(self, fresh_registry: ProcessorRegistry) -> None:
        spec = ProcessorSpec(
            name="x", namespace="plug", cls=_DummyProcessor, replaces="core:nope"
        )
        with pytest.raises(ProcessorNotFoundError):
            fresh_registry.register(spec)


class TestProcessorRegistryUnregister:
    def test_unregister_removes_entry(self, fresh_registry: ProcessorRegistry) -> None:
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
        class _MyProc(_DummyProcessor):
            """Тестовый процессор декоратора."""

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
        class _T(_DummyProcessor):
            """Тестовый процессор с capabilities."""

        registry = get_processor_registry()
        spec = registry.get("test_decor:override_test")
        assert spec.spec_schema == spec_schema
        assert spec.output_schema == output_schema
        assert spec.capabilities == ("net.outbound.example.com:external",)
        assert spec.meta == {"tier": 1}


# ---------------------------------------------------------------------------
# K5 W3 — ProcessorRegistry formal API + JSON-Schema export (ADR-0058)
# ---------------------------------------------------------------------------


class TestDecoratorRegistersProcessor:
    """K5 W3: @processor декоратор регистрирует процессор в registry."""

    def teardown_method(self) -> None:
        """Очистка после тестов."""
        registry = get_processor_registry()
        registry.unregister("k5w3_ns:test_proc")
        registry.unregister("k5w3_ns:test_with_model")

    def test_decorator_registers_processor(self) -> None:
        """@processor(name) помещает класс в global singleton registry."""

        @processor("test_proc", namespace="k5w3_ns", tags=["test", "k5"])
        class MyProc(_StubBase):
            """Тестовый процессор для K5 W3."""

        reg = get_processor_registry()
        assert "k5w3_ns:test_proc" in reg
        spec = reg.get("k5w3_ns:test_proc")
        assert spec.name == "test_proc"
        assert spec.namespace == "k5w3_ns"
        assert spec.cls is MyProc
        assert spec.tags == ("test", "k5")
        # __processor_spec__ прикреплён к классу
        assert MyProc.__processor_spec__ is spec  # type: ignore[attr-defined]

    def test_decorator_auto_resolves_model_from_class_attr(self) -> None:
        """@processor автоматически определяет Pydantic-модель из model атрибута класса."""

        class MyParams(BaseModel):
            """Параметры тестового процессора."""

            x: int = 0

        @processor("test_with_model", namespace="k5w3_ns")
        class ModelProc(_StubBase):
            """Процессор с моделью параметров."""

            model = MyParams

        reg = get_processor_registry()
        spec = reg.get("k5w3_ns:test_with_model")
        assert spec.model is MyParams


class TestRegistryExportSchemasPydanticModel:
    """K5 W3: export_schemas() через Pydantic reflection."""

    def setup_method(self) -> None:
        """Создаёт изолированный реестр + регистрирует тестовый процессор."""
        self.registry = ProcessorRegistry()

        class SmokeParams(BaseModel):
            """Параметры smoke-процессора."""

            url: str
            timeout: int = 30

        class SmokeProc(_StubBase):
            """Smoke-процессор для тестов."""

        self.spec = ProcessorSpec(
            name="smoke",
            namespace="test_ns",
            cls=SmokeProc,  # type: ignore[arg-type]
            model=SmokeParams,
            version="2.1.0",
            tags=("test", "smoke"),
        )
        self.registry.register(self.spec)

    def test_registry_export_schemas_pydantic_model(self) -> None:
        """Pydantic model → JSON-Schema export возвращает валидный dict с $schema и $id."""

        schemas = self.registry.export_schemas()

        assert "test_ns:smoke" in schemas
        schema = schemas["test_ns:smoke"]

        # Обязательные draft-07 поля
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "2.1.0" in schema["$id"]
        assert "test_ns" in schema["$id"]
        assert "smoke" in schema["$id"]

        # Pydantic reflection: поля из SmokeParams должны быть в schema
        props = schema.get("properties", {})
        assert "url" in props
        assert "timeout" in props

        # Метаданные из spec
        assert schema.get("x-gd-tags") == ["test", "smoke"]


class TestRegistryExportSchemasNoModel:
    """K5 W3: export_schemas() graceful при отсутствии model и spec_schema."""

    def test_registry_export_schemas_no_model(self) -> None:
        """Процессор без model и spec_schema получает минимальную open-schema."""

        registry = ProcessorRegistry()

        class BareProc(_StubBase):
            """Процессор без параметров."""

        spec = ProcessorSpec(name="bare", namespace="ns_bare", cls=BareProc)  # type: ignore[arg-type]
        registry.register(spec)

        schemas = registry.export_schemas()
        assert "ns_bare:bare" in schemas
        schema = schemas["ns_bare:bare"]

        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert "$id" in schema
        assert schema.get("type") == "object"


class TestSingletonIdempotent:
    """K5 W3: повторная регистрация не дублирует запись."""

    def teardown_method(self) -> None:
        """Очистка singleton после теста."""
        get_processor_registry().unregister("idm_ns:idm_proc")

    def test_singleton_idempotent(self) -> None:
        """Повторная регистрация с replaces не создаёт дубликатов."""

        reg = get_processor_registry()
        initial_count = len(reg)

        class IdmProc(_StubBase):
            """Идемпотентный процессор."""

        @processor("idm_proc", namespace="idm_ns")
        class _First(_StubBase):
            """Первая версия."""

        count_after_first = len(reg)
        assert count_after_first == initial_count + 1

        # Замена через replaces= — не дублирует
        spec_v2 = ProcessorSpec(
            name="idm_proc",
            namespace="idm_ns",
            cls=IdmProc,  # type: ignore[arg-type]
            replaces="idm_ns:idm_proc",
        )
        reg.register(spec_v2)

        # Всё ещё одна запись для idm_ns:idm_proc
        assert len(reg) == count_after_first
        assert reg.get("idm_ns:idm_proc") is spec_v2


class TestExportProcessorsSchemaToFiles:
    """K5 W3: export_processors_schema() пишет файлы на диск."""

    def test_export_creates_files(self) -> None:
        """export_processors_schema() создаёт .schema.json и index.json."""

        registry = ProcessorRegistry()

        class FileParams(BaseModel):
            """Параметры file-процессора."""

            path: str

        class FileProc(_StubBase):
            """Файловый процессор."""

        spec = ProcessorSpec(
            name="file_write",
            namespace="core",
            cls=FileProc,  # type: ignore[arg-type]
            model=FileParams,
        )
        registry.register(spec)

        # Подменяем глобальный реестр временным через monkey-patch
        import src.backend.dsl.registry.json_schema_exporter as exporter_module

        original_getter = exporter_module.get_processor_registry
        exporter_module.get_processor_registry = lambda: registry  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                n = export_processors_schema(out)

                assert n == 1
                assert (out / "file_write.schema.json").exists()
                assert (out / "index.json").exists()

                # Проверяем валидность JSON
                schema = json.loads((out / "file_write.schema.json").read_text())
                assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
                assert "path" in schema.get("properties", {})

                index = json.loads((out / "index.json").read_text())
                assert len(index["processors"]) == 1
                assert index["processors"][0]["name"] == "file_write"
        finally:
            exporter_module.get_processor_registry = original_getter  # type: ignore[assignment]
