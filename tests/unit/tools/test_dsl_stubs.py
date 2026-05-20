# ruff: noqa: S101
"""Sprint 14 K3 W2 — unit-тесты ``tools.gen_dsl_stubs``."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import gen_dsl_stubs as gds  # noqa: E402


class _Demo:
    """Тестовый класс."""

    def public_a(self, x: int) -> str:
        """Метод A."""
        return str(x)

    def public_b(self, *args: int, **kwargs: int) -> int:
        """Метод B."""
        return sum(args) + sum(kwargs.values())

    def _private(self) -> None:
        """Не должен попасть в stub."""

    @staticmethod
    def static_one(x: int) -> int:
        return x


def test_collect_public_methods_includes_only_public() -> None:
    methods = gds._collect_public_methods(_Demo)
    names = {m.name for m in methods}
    assert "public_a" in names
    assert "public_b" in names
    assert "_private" not in names
    # static_one должен быть собран
    assert "static_one" in names


def test_render_stub_contains_class_and_methods() -> None:
    methods = gds._collect_public_methods(_Demo)
    stub = gds.render_stub("test.demo", "Demo", methods)
    assert "class Demo:" in stub
    assert "def public_a" in stub
    assert "def public_b" in stub


def test_generate_stub_for_route_builder() -> None:
    content = gds.generate_stub(
        "src.backend.dsl.builders.base",
        "RouteBuilder",
        Path("/tmp/route_builder.pyi"),
    )
    assert "class RouteBuilder:" in content
    # Поле public-методов содержит как минимум один метод с глаголом-действием.
    # Не привязываем к конкретным именам, чтобы тест не падал при рефакторингах.
    assert content.count("def ") >= 5


def test_generate_stub_for_workflow_builder() -> None:
    content = gds.generate_stub(
        "src.backend.dsl.workflow.builder",
        "WorkflowBuilder",
        Path("/tmp/workflow_builder.pyi"),
    )
    assert "class WorkflowBuilder:" in content


def test_coverage_route_builder_at_least_10_methods() -> None:
    """DoD §S14.9: 100% public methods; smoke-проверим что собрали хотя бы 10."""
    import importlib

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    module = importlib.import_module("src.backend.dsl.builders.base")
    methods = gds._collect_public_methods(module.RouteBuilder)
    assert len(methods) >= 10
