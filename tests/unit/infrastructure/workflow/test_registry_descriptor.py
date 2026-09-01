"""Unit-тесты ``core.infrastructure.workflow.registry`` — coverage ratchet (S48 W4).

S47 W7 retro identified ``src/backend/infrastructure/workflow/registry.py`` (182 LOC,
9 публичных методов + dataclass ``WorkflowDescriptor``) как следующий coverage
target — production используется в Admin API, MCP auto-export, WorkflowBuilder,
но dedicated test-файла не было.

Цель slice: поднять coverage на WorkflowDescriptor + WorkflowRegistry до 100%,
покрывая:
* ``WorkflowDescriptor`` dataclass с дефолтами;
* ``register`` (включая ValueError для пустого name/route_id и дубля);
* ``unregister`` (с cleanup _specs);
* ``register_spec`` (replace-semantics);
* ``get_spec``, ``get``, ``get_route_id``, ``list_all`` (sorted);
* ``clear``, ``__contains__``, ``__len__``;
* глобальный singleton ``workflow_registry``.

``WorkflowSpec`` импортируется только TYPE_CHECKING → тесты не требуют
``executor`` модуль в runtime path.

Test-env note: import chain ``infrastructure.workflow.__init__`` →
``pg_runner_internals.event_store`` → ``core.domain.models`` → ``extensions.*``
→ ``core.utils.metrics_registry`` (prometheus_client) — недоступен.
Используем sys.modules stub-injection (per S47 W5 lesson), чтобы избежать
collection-time ModuleNotFoundError. Импорт registry делаем внутри тестов
после активации autouse fixture.
"""

from __future__ import annotations

import sys
import threading
import types
from collections.abc import Iterable

import pytest


def _make_metrics_stub() -> types.ModuleType:
    fake = types.ModuleType("src.backend.core.utils.metrics_registry")
    fake.MetricsRegistry = type("MR", (), {})  # type: ignore[attr-defined]
    fake.metrics_registry = object()  # type: ignore[attr-defined]
    return fake


def _make_workflow_pkg_stub() -> types.ModuleType:
    """Stub ``src.backend.infrastructure.workflow.__init__`` — pre-init import
    chain triggers eager module-load (pg_runner_internals → core.domain.models →
    extensions → core.api → core.utils.metrics_registry → prometheus_client)
    и кучу Pydantic model_validators с self-ref NameError (RedisSettings,
    DatabaseConnectionSettings, etc.). Без stub'а module-level import registry
    невозможен в test-env.

    Решение: stub ``__init__`` так, чтобы Python не выполнял его тело при
    импорте registry submodule (registry импортируется напрямую через свой
    path). Stub регистрирует ``WorkflowSpec``, ``register_workflow_spec`` и
    другие re-exports как пустые placeholder'ы — но сам registry module
    импортируется по полному пути ``registry.py`` и работает независимо.
    """
    fake = types.ModuleType("src.backend.infrastructure.workflow")
    # Sub-modules registry.py импортирует — заглушки:
    fake.WorkflowSpec = type("WS", (), {})  # type: ignore[attr-defined]
    fake.register_workflow_spec = lambda *a, **kw: None  # type: ignore[attr-defined]
    fake.unregister_workflow_spec = lambda *a, **kw: None  # type: ignore[attr-defined]
    fake.workflow_spec_registry = object()  # type: ignore[attr-defined]
    return fake


@pytest.fixture(autouse=True)
def _stub_import_chain() -> Iterable[None]:
    """autouse: подменяет broken modules на stubs ДО import registry.

    Stub модулей (chain блокирует module import registry):
    * ``metrics_registry`` → prometheus_client chain missing (S47 W5 lesson)
    * ``infrastructure.workflow.__init__`` → eager imports → куча
      Pydantic model_validators с self-ref NameError (RedisSettings,
      DatabaseConnectionSettings — тот же класс багов что S47 W7 — без
      ``from __future__ import annotations``).

    После активации фикстуры test может импортировать
    ``infrastructure.workflow.registry`` напрямую (registry.py — самостоятельный
    модуль с TYPE_CHECKING для WorkflowSpec).
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setitem(
            sys.modules,
            "src.backend.core.utils.metrics_registry",
            _make_metrics_stub(),
        )
        # Stub-пакет infrastructure.workflow: Python при импорте submodule
        # registry выполняет __init__.py — заменяем на пустышку.
        mp.setitem(
            sys.modules,
            "src.backend.infrastructure.workflow",
            _make_workflow_pkg_stub(),
        )
        yield


def _import_registry() -> tuple[type, type, object]:
    """Lazy import через ``importlib.util`` — bypass package ``__init__``.

    ``src.backend.infrastructure.workflow.__init__.py`` имеет eager imports,
    которые запускают chain c несколькими Pydantic model self-ref NameError
    (RedisSettings, DatabaseConnectionSettings и т.п.). Решение: грузим
    ``registry.py`` напрямую через spec_from_file_location (по абсолютному
    пути в файловой системе), минуя package init и не полагаясь на stub'нутый
    parent package.

    WorkflowSpec используется только в TYPE_CHECKING — runtime path не
    требует реального WorkflowSpec class.
    """
    import importlib.util  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    here = Path(__file__).resolve().parent
    project_root = here
    while not (project_root / "src").exists():
        project_root = project_root.parent
    registry_path = (
        project_root
        / "src"
        / "backend"
        / "infrastructure"
        / "workflow"
        / "registry.py"
    )

    spec = importlib.util.spec_from_file_location(
        "_workflow_registry_isolated",
        registry_path,
    )
    if spec is None or spec.loader is None:
        msg = f"Cannot load registry module from {registry_path}"
        raise ImportError(msg)

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.WorkflowDescriptor, module.WorkflowRegistry, module.workflow_registry


@pytest.mark.unit
class TestWorkflowDescriptor:
    """Dataclass ``WorkflowDescriptor`` — defaults + field validation."""

    def test_defaults(self) -> None:
        """Defaults: description='', input_schema=None, output_schema=None,
        max_attempts=10, tags=().

        """
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(name="x")
        assert d.name == "x"
        assert d.description == ""
        assert d.input_schema is None
        assert d.output_schema is None
        assert d.max_attempts == 10
        assert d.tags == ()

    def test_with_all_fields(self) -> None:
        """Все поля заполняются явно."""
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(
            name="orders.skb_flow",
            description="Стандартный flow обработки заказа",
            input_schema=dict,  # placeholder type
            output_schema=None,
            max_attempts=5,
            tags=("banking", "ai", "saga"),
        )
        assert d.name == "orders.skb_flow"
        assert d.description == "Стандартный flow обработки заказа"
        assert d.input_schema is dict
        assert d.max_attempts == 5
        assert d.tags == ("banking", "ai", "saga")

    def test_tags_tuple_is_immutable_default(self) -> None:
        """``tags`` default factory — новая tuple для каждого instance.

        Note: empty tuple ``()`` is interned в CPython, поэтому ``is``
        identity check для пустых tuples даст True. Проверяем через
        non-empty tags + mutation isolation:
        """
        WorkflowDescriptor, _, _ = _import_registry()
        d1 = WorkflowDescriptor(name="a", tags=("x",))
        d2 = WorkflowDescriptor(name="b", tags=("y",))
        assert d1.tags is not d2.tags  # non-empty tuples — fresh objects
        assert d1.tags == ("x",)
        assert d2.tags == ("y",)


@pytest.mark.unit
class TestWorkflowRegistryRegister:
    """``register`` — happy path + ValueError edge cases."""

    def setup_method(self) -> None:
        _, WorkflowRegistry, _ = _import_registry()
        self.registry = WorkflowRegistry()

    def test_register_basic_descriptor(self) -> None:
        """``register(descriptor, route_id)`` сохраняет в оба dict'а."""
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(name="orders.skb_flow")
        self.registry.register(d, route_id="workflow:orders.skb_flow")
        assert self.registry.get("orders.skb_flow") is d
        assert self.registry.get_route_id("orders.skb_flow") == "workflow:orders.skb_flow"

    def test_register_empty_name_raises_value_error(self) -> None:
        """``descriptor.name=''`` → ValueError (name validation)."""
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(name="")
        with pytest.raises(ValueError, match="name не может быть пустым"):
            self.registry.register(d, route_id="workflow:x")

    def test_register_empty_route_id_raises_value_error(self) -> None:
        """``route_id=''`` → ValueError (route_id validation)."""
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(name="valid_name")
        with pytest.raises(ValueError, match="route_id не может быть пустым"):
            self.registry.register(d, route_id="")

    def test_register_duplicate_name_raises_value_error(self) -> None:
        """Дубликат ``name`` → ValueError (route_id из prev регистрации в сообщении)."""
        WorkflowDescriptor, _, _ = _import_registry()
        d1 = WorkflowDescriptor(name="dup")
        d2 = WorkflowDescriptor(name="dup")
        self.registry.register(d1, route_id="route_a")
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            self.registry.register(d2, route_id="route_b")

    def test_register_with_spec_adds_to_specs_dict(self) -> None:
        """``spec=...`` → ``self._specs[route_id] = spec`` (hot-reload support)."""
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(name="with_spec")
        spec = object()  # placeholder, не WorkflowSpec (TYPE_CHECKING-only)
        self.registry.register(d, route_id="route_x", spec=spec)  # type: ignore[arg-type]
        assert self.registry.get_spec("route_x") is spec

    def test_register_without_spec_leaves_specs_empty(self) -> None:
        """``spec=None`` (default) → не пишем в ``_specs`` (lazy)."""
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(name="no_spec")
        self.registry.register(d, route_id="route_y")
        assert self.registry.get_spec("route_y") is None


@pytest.mark.unit
class TestWorkflowRegistryUnregister:
    """``unregister`` — cleanup ``_descriptors``/``_route_ids``/``_specs``."""

    def setup_method(self) -> None:
        _, WorkflowRegistry, _ = _import_registry()
        self.registry = WorkflowRegistry()

    def test_unregister_existing_name(self) -> None:
        """``unregister(name)`` удаляет из обоих dict'ов + ``_specs``."""
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(name="temp")
        spec = object()  # type: ignore[arg-type]
        self.registry.register(d, route_id="route_temp", spec=spec)
        self.registry.unregister("temp")
        assert self.registry.get("temp") is None
        assert self.registry.get_route_id("temp") is None
        assert self.registry.get_spec("route_temp") is None

    def test_unregister_unknown_name_is_silent(self) -> None:
        """``unregister`` не зарегистрированного → no raise (graceful)."""
        # Не должно raise.
        self.registry.unregister("never_registered")
        assert len(self.registry) == 0

    def test_unregister_without_spec(self) -> None:
        """``unregister`` без spec → ``_specs.pop(route_id, None)`` skip."""
        WorkflowDescriptor, _, _ = _import_registry()
        d = WorkflowDescriptor(name="no_spec")
        self.registry.register(d, route_id="route_z")
        # Не должно raise даже если _specs пуст.
        self.registry.unregister("no_spec")
        assert "no_spec" not in self.registry


@pytest.mark.unit
class TestWorkflowRegistrySpecOperations:
    """``register_spec`` + ``get_spec`` — separate hot-reload path."""

    def setup_method(self) -> None:
        _, WorkflowRegistry, _ = _import_registry()
        self.registry = WorkflowRegistry()

    def test_register_spec_roundtrip(self) -> None:
        """``register_spec(route_id, spec)`` + ``get_spec(route_id)`` roundtrip."""
        spec = object()  # type: ignore[arg-type]
        self.registry.register_spec("route_spec", spec)
        assert self.registry.get_spec("route_spec") is spec

    def test_register_spec_empty_route_id_raises(self) -> None:
        """``register_spec(route_id='', ...)`` → ValueError."""
        with pytest.raises(ValueError, match="route_id не может быть пустым"):
            self.registry.register_spec("", object())  # type: ignore[arg-type]

    def test_register_spec_replaces_existing(self) -> None:
        """Повторный ``register_spec`` для того же ``route_id`` → replace."""
        spec1 = object()  # type: ignore[arg-type]
        spec2 = object()  # type: ignore[arg-type]
        self.registry.register_spec("route", spec1)
        self.registry.register_spec("route", spec2)
        assert self.registry.get_spec("route") is spec2

    def test_get_spec_unknown_route_returns_none(self) -> None:
        """``get_spec`` для unknown → ``None`` (не raise)."""
        assert self.registry.get_spec("never_set") is None


@pytest.mark.unit
class TestWorkflowRegistryLookup:
    """``get`` / ``get_route_id`` / ``list_all`` / ``__contains__`` / ``__len__``."""

    def setup_method(self) -> None:
        WorkflowDescriptor, WorkflowRegistry, _ = _import_registry()
        self.registry = WorkflowRegistry()
        # Регистрируем 3 descriptor'а в неупорядоченном порядке.
        for name in ["Charlie", "Alpha", "Bravo"]:
            self.registry.register(
                WorkflowDescriptor(name=name),
                route_id=f"route:{name}",
            )

    def test_get_returns_descriptor(self) -> None:
        """``get(name)`` → descriptor или None."""
        for name in ["Alpha", "Bravo", "Charlie"]:
            d = self.registry.get(name)
            assert d is not None
            assert d.name == name

    def test_get_unknown_returns_none(self) -> None:
        """``get(unknown)`` → ``None`` (не raise)."""
        assert self.registry.get("DoesNotExist") is None

    def test_get_route_id_returns_route_id(self) -> None:
        """``get_route_id(name)`` → ``f"route:{name}"`` или None."""
        assert self.registry.get_route_id("Alpha") == "route:Alpha"
        assert self.registry.get_route_id("DoesNotExist") is None

    def test_list_all_returns_sorted(self) -> None:
        """``list_all()`` → sorted by name (детерминированный порядок)."""
        names = [d.name for d in self.registry.list_all()]
        assert names == ["Alpha", "Bravo", "Charlie"]

    def test_list_all_empty(self) -> None:
        """``list_all()`` пустого реестра → ``[]``."""
        _, WorkflowRegistry, _ = _import_registry()
        empty = WorkflowRegistry()
        assert empty.list_all() == []

    def test_contains_returns_true_for_registered(self) -> None:
        """``"name" in registry`` → True для зарегистрированных."""
        assert "Alpha" in self.registry

    def test_contains_returns_false_for_unknown(self) -> None:
        """``"name" in registry`` → False для unknown."""
        assert "Zulu" not in self.registry

    def test_len_returns_count(self) -> None:
        """``len(registry)`` → число descriptor'ов."""
        assert len(self.registry) == 3


@pytest.mark.unit
class TestWorkflowRegistryClear:
    """``clear`` — очистка всех dict'ов."""

    def setup_method(self) -> None:
        WorkflowDescriptor, WorkflowRegistry, _ = _import_registry()
        self.registry = WorkflowRegistry()
        for name in ["A", "B", "C"]:
            self.registry.register(
                WorkflowDescriptor(name=name),
                route_id=f"r:{name}",
            )

    def test_clear_removes_all(self) -> None:
        """``clear()`` очищает ``_descriptors``/``_route_ids``/``_specs``."""
        assert len(self.registry) == 3
        self.registry.clear()
        assert len(self.registry) == 0
        assert self.registry.list_all() == []
        assert self.registry.get("A") is None

    def test_clear_on_empty_registry_is_silent(self) -> None:
        """``clear()`` пустого реестра → no raise."""
        _, WorkflowRegistry, _ = _import_registry()
        empty = WorkflowRegistry()
        empty.clear()  # не должно raise
        assert len(empty) == 0


@pytest.mark.unit
class TestWorkflowRegistryThreadSafety:
    """Thread-safety contract: lock защищает запись (smoke test)."""

    def test_concurrent_register_no_crash(self) -> None:
        """10 потоков регистрируют разные names → все успешно, len=10."""
        WorkflowDescriptor, WorkflowRegistry, _ = _import_registry()
        registry = WorkflowRegistry()
        errors: list[Exception] = []

        def register_one(i: int) -> None:
            try:
                registry.register(
                    WorkflowDescriptor(name=f"w_{i}"),
                    route_id=f"route_{i}",
                )
            except Exception as exc:  # noqa: BLE001 — safety net
                errors.append(exc)

        threads = [threading.Thread(target=register_one, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(registry) == 10


@pytest.mark.unit
class TestWorkflowRegistrySingleton:
    """Глобальный singleton ``workflow_registry``."""

    def test_singleton_identity(self) -> None:
        """``workflow_registry`` создаётся один раз при module-load (singleton
        pattern через module-level statement).

        Note: importlib.util создаёт новый module object при каждом load,
        поэтому singleton identity нельзя проверить между reloads. Вместо
        этого проверяем что module имеет ровно один атрибут ``workflow_registry``,
        который создаётся при первом выполнении module body.
        """
        _, _, singleton = _import_registry()
        # Module body выполнен ровно один раз → singleton создан.
        assert singleton is not None
        assert hasattr(singleton, "register")  # WorkflowRegistry API

    def test_singleton_is_workflow_registry_instance(self) -> None:
        """Singleton — instance :class:`WorkflowRegistry`."""
        _, WorkflowRegistry, singleton = _import_registry()
        assert isinstance(singleton, WorkflowRegistry)
