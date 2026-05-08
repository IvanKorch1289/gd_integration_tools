"""Тесты :class:`WorkflowCompilerRegistry` (compiler-level кэш).

Проверяют:
* :meth:`get_or_compile` — cache-hit при повторных вызовах с тем же decl;
* :meth:`replace` — force recompile;
* :meth:`snapshot` / :meth:`restore` — atomic rollback;
* :meth:`bulk_register` — пересборка списка;
* :meth:`unregister` / :meth:`clear`.
"""
# ruff: noqa: S101

from __future__ import annotations

from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.compiler.registry import WorkflowCompilerRegistry


def _decl(name: str = "test.flow") -> object:
    return WorkflowBuilder(name).activity("foo.bar").build()


def test_get_returns_none_when_not_compiled() -> None:
    reg = WorkflowCompilerRegistry()
    assert reg.get("missing") is None


def test_get_or_compile_caches_identical_declaration() -> None:
    reg = WorkflowCompilerRegistry()
    decl = _decl()
    a = reg.get_or_compile(decl)
    b = reg.get_or_compile(decl)
    assert a is b
    assert reg.get(decl.name) is a  # type: ignore[attr-defined]


def test_get_or_compile_recompiles_when_declaration_changed() -> None:
    reg = WorkflowCompilerRegistry()
    decl_v1 = _decl()
    a = reg.get_or_compile(decl_v1)
    # Меняем декларацию: тот же name, но другие шаги.
    decl_v2 = WorkflowBuilder(decl_v1.name).activity("foo.bar").activity("foo.baz").build()  # type: ignore[attr-defined]
    b = reg.get_or_compile(decl_v2)
    assert a is not b


def test_replace_forces_recompile() -> None:
    reg = WorkflowCompilerRegistry()
    decl = _decl()
    a = reg.get_or_compile(decl)
    b = reg.replace(decl)
    assert a is not b
    assert reg.get(decl.name) is b  # type: ignore[attr-defined]


def test_unregister_removes_from_cache() -> None:
    reg = WorkflowCompilerRegistry()
    decl = _decl()
    reg.get_or_compile(decl)
    assert reg.unregister(decl.name) is True  # type: ignore[attr-defined]
    assert reg.get(decl.name) is None  # type: ignore[attr-defined]
    # Повторный unregister — False.
    assert reg.unregister(decl.name) is False  # type: ignore[attr-defined]


def test_list_compiled_returns_tuple_of_all_compiled() -> None:
    reg = WorkflowCompilerRegistry()
    reg.get_or_compile(_decl("a.first"))
    reg.get_or_compile(_decl("b.second"))
    compiled = reg.list_compiled()
    assert len(compiled) == 2
    assert {c.name for c in compiled} == {"a.first", "b.second"}


def test_list_names_returns_sorted_tuple() -> None:
    reg = WorkflowCompilerRegistry()
    reg.get_or_compile(_decl("zeta"))
    reg.get_or_compile(_decl("alpha"))
    reg.get_or_compile(_decl("mid"))
    assert reg.list_names() == ("alpha", "mid", "zeta")


def test_snapshot_and_restore_roundtrip() -> None:
    reg = WorkflowCompilerRegistry()
    decl_a = _decl("a")
    reg.get_or_compile(decl_a)
    snap = reg.snapshot()

    reg.get_or_compile(_decl("b"))
    assert "b" in reg.list_names()

    reg.restore(snap)
    assert reg.list_names() == ("a",)


def test_bulk_register_compiles_all() -> None:
    reg = WorkflowCompilerRegistry()
    declarations = [_decl("first"), _decl("second"), _decl("third")]
    compiled = reg.bulk_register(declarations)
    assert [c.name for c in compiled] == ["first", "second", "third"]
    assert reg.list_names() == ("first", "second", "third")


def test_bulk_register_replaces_existing() -> None:
    reg = WorkflowCompilerRegistry()
    decl_v1 = _decl("flow")
    a = reg.get_or_compile(decl_v1)
    # bulk_register с тем же name → replace.
    [b] = reg.bulk_register([decl_v1])
    assert a is not b


def test_clear_empties_the_registry() -> None:
    reg = WorkflowCompilerRegistry()
    reg.get_or_compile(_decl("a"))
    reg.get_or_compile(_decl("b"))
    reg.clear()
    assert reg.list_names() == ()
    assert reg.list_compiled() == ()
