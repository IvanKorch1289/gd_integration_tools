# ruff: noqa: S101
"""Тесты ``MiddlewareRegistry`` (S17 ADR-NEW-2).

Покрывают регистрацию built-in / plugin.toml / entry-points, порядок
``apply_to_app`` по ``order``, ``render_tree``-форматирование и
per-route override через ``route_overrides``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.backend.entrypoints.middlewares.registry import (
    MiddlewareRegistry,
    MiddlewareSpec,
)


class _DummyMiddleware:
    """Stand-in ASGI middleware для тестов (signature не важна)."""

    def __init__(self, app: Any, **options: Any) -> None:
        self.app = app
        self.options = options


class _OtherMiddleware(_DummyMiddleware):
    """Второй stand-in для проверки порядка."""


@dataclass
class _FakeApp:
    """Минимальный stand-in FastAPI.add_middleware."""

    middlewares: list[tuple[type, dict[str, Any]]] = field(default_factory=list)

    def add_middleware(self, cls: type, **options: Any) -> None:
        self.middlewares.append((cls, options))


class TestRegisterBuiltin:
    def test_register_builtin_orders_by_layer(self) -> None:
        """``apply_to_app`` итерируется по spec'ам в порядке возрастания order."""
        registry = MiddlewareRegistry()
        registry.register_builtin("a", _DummyMiddleware, order=300)
        registry.register_builtin("b", _OtherMiddleware, order=100)
        app = _FakeApp()
        applied = registry.apply_to_app(app)
        assert applied == ("b", "a")
        assert [cls for cls, _ in app.middlewares] == [
            _OtherMiddleware,
            _DummyMiddleware,
        ]


class TestRegisterFromToml:
    def test_register_from_toml_appends(self) -> None:
        """``register_from_toml`` принимает [[middleware]]-секции и добавляет spec'и."""
        registry = MiddlewareRegistry()
        registry.register_from_toml(
            "demo_plugin",
            [
                {
                    "name": "demo",
                    "module": f"{_DummyMiddleware.__module__}:_DummyMiddleware",
                    "order": 700,
                    "options": {"x": 1},
                    "enabled_routes": ["/api/v1/*"],
                }
            ],
        )
        specs = registry.specs()
        assert len(specs) == 1
        spec = specs[0]
        assert spec.name == "demo"
        assert spec.middleware_cls.__qualname__ == "_DummyMiddleware"
        assert spec.order == 700
        assert spec.options == {"x": 1}
        assert spec.enabled_routes == ("/api/v1/*",)
        assert spec.source == "plugin:demo_plugin"

    def test_register_from_toml_rejects_invalid(self) -> None:
        """Запись без ``name``/``module`` → ValueError с указанием плагина."""
        registry = MiddlewareRegistry()
        with pytest.raises(ValueError, match="demo_plugin"):
            registry.register_from_toml("demo_plugin", [{"name": "x"}])


class TestRegisterFromEntryPoints:
    def test_register_from_entry_point_appends(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Monkey-patched entry_points возвращает spec через register_from_entry_points."""

        class _FakeDist:
            name = "fake-dist"

        class _FakeEP:
            name = "demo_ep"
            dist = _FakeDist()

            def load(self) -> type:
                return _DummyMiddleware

        def fake_entry_points(group: str) -> tuple[_FakeEP, ...]:
            assert group == "gd_integration_tools.middleware_hooks"
            return (_FakeEP(),)

        monkeypatch.setattr("importlib.metadata.entry_points", fake_entry_points)
        registry = MiddlewareRegistry()
        registry.register_from_entry_points()
        specs = registry.specs()
        assert len(specs) == 1
        assert specs[0].name == "demo_ep"
        assert specs[0].middleware_cls is _DummyMiddleware
        assert specs[0].source == "entry_point:fake-dist"


class TestApplyToApp:
    def test_apply_to_app_respects_order(self) -> None:
        """Spec'и применяются в порядке возрастания ``order``."""
        registry = MiddlewareRegistry()
        registry.register_builtin("third", _DummyMiddleware, order=900)
        registry.register_builtin("first", _DummyMiddleware, order=100)
        registry.register_builtin("second", _OtherMiddleware, order=500)
        app = _FakeApp()
        applied = registry.apply_to_app(app)
        assert applied == ("first", "second", "third")


class TestRenderTree:
    def test_render_tree_format(self) -> None:
        """``render_tree`` группирует по слоям и форматирует одной строкой на spec."""
        registry = MiddlewareRegistry()
        registry.register_builtin("early", _DummyMiddleware, order=50)
        registry.register_builtin("late", _OtherMiddleware, order=800)
        tree = registry.render_tree()
        assert "Layer 1 (early exit, 0-249):" in tree
        assert "Layer 4 (logging/metrics, 750-999):" in tree
        assert "[050] early" in tree
        assert "[800] late" in tree


class TestPerRouteOverride:
    def test_per_route_override_disable_skips_middleware(self) -> None:
        """``route_overrides[name].enabled=False`` исключает middleware из chain'а."""
        registry = MiddlewareRegistry()
        registry.register_builtin("keep", _DummyMiddleware, order=100)
        registry.register_builtin("skip", _OtherMiddleware, order=200)
        app = _FakeApp()
        applied = registry.apply_to_app(
            app, route_overrides={"skip": {"enabled": False}}
        )
        assert applied == ("keep",)
        assert [cls for cls, _ in app.middlewares] == [_DummyMiddleware]

    def test_per_route_override_merges_options(self) -> None:
        """``route_overrides[name].options`` мерджится поверх spec.options."""
        registry = MiddlewareRegistry()
        registry.register_builtin("m", _DummyMiddleware, {"a": 1, "b": 2}, order=100)
        app = _FakeApp()
        registry.apply_to_app(
            app, route_overrides={"m": {"options": {"b": 99, "c": 3}}}
        )
        cls, options = app.middlewares[0]
        assert cls is _DummyMiddleware
        assert options == {"a": 1, "b": 99, "c": 3}


def test_middleware_spec_defaults_are_immutable() -> None:
    """``MiddlewareSpec`` — frozen dataclass с slots."""
    spec = MiddlewareSpec(name="x", middleware_cls=_DummyMiddleware)
    assert spec.order == 500
    assert spec.options == {}
    assert spec.enabled_routes == ()
    assert spec.source == "builtin"
    with pytest.raises(AttributeError):
        spec.name = "y"  # type: ignore[misc]
