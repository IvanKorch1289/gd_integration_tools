"""Unit-тесты LazyProcessorRegistry (Sprint 9 K3 W3)."""

from __future__ import annotations

import pytest

from src.backend.dsl.registry.errors import ProcessorNotFoundError
from src.backend.dsl.registry.lazy_processor import (
    LazyProcessorRef,
    LazyProcessorRegistry,
    load_processor_class,
)


class _FakeSpec:
    def __init__(self, fqn: str, capabilities: tuple[str, ...] = ()) -> None:
        self.fqn = fqn
        self.capabilities = capabilities


class _FakeBaseRegistry:
    def __init__(self) -> None:
        self._store: dict[str, _FakeSpec] = {}

    def register(self, spec: _FakeSpec) -> _FakeSpec:
        self._store[spec.fqn] = spec
        return spec

    def get(self, fqn: str) -> _FakeSpec:
        if fqn not in self._store:
            raise ProcessorNotFoundError(fqn)
        return self._store[fqn]


def test_register_lazy_does_not_import() -> None:
    base = _FakeBaseRegistry()
    lazy = LazyProcessorRegistry(base=base)
    ref = lazy.register_lazy(
        name="x",
        namespace="core",
        module_path="some.module:Cls",
        capabilities=("cap.a",),
    )
    assert ref.fqn == "core:x"
    assert ref.capabilities == ("cap.a",)
    assert lazy.list_unresolved() == [ref]


def test_capabilities_for_lazy_ref() -> None:
    base = _FakeBaseRegistry()
    lazy = LazyProcessorRegistry(base=base)
    lazy.register_lazy(
        name="y", namespace="core", module_path="m:Y", capabilities=("cap.x", "cap.y")
    )
    assert lazy.capabilities_for("core:y") == ("cap.x", "cap.y")


def test_capabilities_fallback_to_base() -> None:
    base = _FakeBaseRegistry()
    base.register(_FakeSpec("core:z", capabilities=("base.cap",)))
    lazy = LazyProcessorRegistry(base=base)
    assert lazy.capabilities_for("core:z") == ("base.cap",)


def test_capabilities_returns_empty_when_unknown() -> None:
    lazy = LazyProcessorRegistry(base=_FakeBaseRegistry())
    assert lazy.capabilities_for("core:unknown") == ()


def test_resolve_returns_base_spec_if_already_registered() -> None:
    base = _FakeBaseRegistry()
    base.register(_FakeSpec("core:already"))
    lazy = LazyProcessorRegistry(base=base)
    spec = lazy.resolve("core:already")
    assert spec.fqn == "core:already"


def test_resolve_unknown_raises() -> None:
    lazy = LazyProcessorRegistry(base=_FakeBaseRegistry())
    with pytest.raises(ProcessorNotFoundError):
        lazy.resolve("core:nothing")


def test_load_processor_class_imports_attribute() -> None:
    cls = load_processor_class("os.path:join")
    import os

    assert cls is os.path.join


def test_load_processor_class_bad_path_raises() -> None:
    with pytest.raises(ImportError):
        load_processor_class("no_colon_module")


def test_resolve_imports_module_and_registers(tmp_path, monkeypatch) -> None:
    """Лениво загруженный модуль → ref считается resolved."""
    base = _FakeBaseRegistry()
    lazy = LazyProcessorRegistry(base=base)

    # Создаём фейковый модуль с processor-like
    fake_module = tmp_path / "fake_lazy_proc.py"
    fake_module.write_text(
        "class FakeProc:\n    fqn = 'core:fake'\n    capabilities = ()\n\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    lazy.register_lazy(
        name="fake", namespace="core", module_path="fake_lazy_proc:FakeProc"
    )
    # До resolve в base нет
    with pytest.raises(ProcessorNotFoundError):
        base.get("core:fake")

    # Симулируем регистрацию в base (как делал бы @processor decorator)
    base.register(_FakeSpec("core:fake"))
    spec = lazy.resolve("core:fake")
    assert spec.fqn == "core:fake"
    assert lazy.list_unresolved() == []
