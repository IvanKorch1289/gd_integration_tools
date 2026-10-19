"""Tests for ``src.backend.core.di.providers.notifications``.

S170 NEW (Milestone 1) — notification gateway provider с test-override.
"""

from __future__ import annotations

import pytest

from src.backend.core.di.providers import notifications
from src.backend.core.di.providers.notifications import (
    get_notification_gateway,
    set_notification_gateway,
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    """Гарантируем чистый _overrides между тестами."""
    notifications._overrides.clear()
    yield
    notifications._overrides.clear()


class TestGetNotificationGateway:
    """get_notification_gateway() — singleton + override resolution."""

    def test_returns_value_from_overrides(self) -> None:
        sentinel = object()
        notifications._overrides["notifications"] = sentinel
        assert get_notification_gateway() is sentinel

    def test_set_notification_gateway_injects_override(self) -> None:
        sentinel = object()
        set_notification_gateway(sentinel)
        assert get_notification_gateway() is sentinel

    def test_set_notification_gateway_persists(self) -> None:
        sentinel = object()
        set_notification_gateway(sentinel)
        # Повторный вызов — то же значение
        assert get_notification_gateway() is sentinel

    def test_overrides_dict_used_when_key_present(self) -> None:
        sentinel_a = object()
        sentinel_b = object()
        set_notification_gateway(sentinel_a)
        assert get_notification_gateway() is sentinel_a
        # Перезапись
        notifications._overrides["notifications"] = sentinel_b
        assert get_notification_gateway() is sentinel_b


class TestModuleExports:
    """Проверка __all__."""

    def test_all_contains_getter_and_setter(self) -> None:
        assert "get_notification_gateway" in notifications.__all__
        assert "set_notification_gateway" in notifications.__all__
        assert len(notifications.__all__) == 2

    def test_module_imports(self) -> None:
        # Smoke import — module is importable and resolvable
        from src.backend.core.di.providers import notifications as _mod

        assert _mod is notifications


class TestResolveModuleBranch:
    """Когда override отсутствует — get_notification_gateway() вызывает
    resolve_module('infrastructure.notifications.gateway').get_gateway().
    """

    def test_calls_resolve_module_when_no_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"yes": False}

        class FakeGateway:
            pass

        class FakeModule:
            def get_gateway(self) -> FakeGateway:
                called["yes"] = True
                return FakeGateway()

        def fake_resolve_module(name: str):
            assert name == "infrastructure.notifications.gateway"
            return FakeModule()

        monkeypatch.setattr(notifications, "resolve_module", fake_resolve_module)
        result = get_notification_gateway()
        assert called["yes"] is True
        assert isinstance(result, FakeGateway)


class TestTypeAnnotation:
    """Type hints корректные (Any для гибкости в DI)."""

    def test_getter_returns_any(self) -> None:
        import inspect

        hints = inspect.get_annotations(get_notification_gateway)
        assert "return" in hints

    def test_setter_accepts_any(self) -> None:
        import inspect

        hints = inspect.get_annotations(set_notification_gateway)
        assert "gateway" in hints