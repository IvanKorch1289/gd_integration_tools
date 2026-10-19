"""Tests for ``src.backend.core.di.providers.workflow._notifications``.

W9 P2-13 Phase 7: workflow_factory_module + notifications_module providers
extracted from god-module.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.di.providers.workflow import _notifications as mod
from src.backend.core.di.providers.workflow._notifications import (
    get_notifications_module_provider,
    get_workflow_factory_module_provider,
    set_notifications_module_provider,
    set_workflow_factory_module_provider,
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    """Чистим _overrides между тестами."""
    mod._overrides.clear()
    yield
    mod._overrides.clear()


class TestGetWorkflowFactoryModuleProvider:
    """get_workflow_factory_module_provider — workflow.factory alias."""

    def test_override_returns_sentinel(self) -> None:
        sentinel = object()
        set_workflow_factory_module_provider(sentinel)
        assert get_workflow_factory_module_provider() is sentinel

    def test_overrides_dict_short_circuits(self) -> None:
        sentinel = object()
        mod._overrides["workflow_factory_module"] = sentinel
        result = get_workflow_factory_module_provider()
        assert result is sentinel

    def test_no_override_calls_resolve_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"yes": False}

        def fake_resolve(name: str) -> Any:
            assert name == "workflow.factory"
            called["yes"] = True
            return MagicMock(name="workflow.factory")

        monkeypatch.setattr(mod, "resolve_module", fake_resolve)
        result = get_workflow_factory_module_provider()
        assert called["yes"] is True
        assert result is not None


class TestSetWorkflowFactoryModuleProvider:
    """set_workflow_factory_module_provider — test-override."""

    def test_persists_value(self) -> None:
        sentinel = object()
        set_workflow_factory_module_provider(sentinel)
        # Повторный get — то же значение
        assert get_workflow_factory_module_provider() is sentinel

    def test_overwrites_previous(self) -> None:
        a = object()
        b = object()
        set_workflow_factory_module_provider(a)
        set_workflow_factory_module_provider(b)
        assert get_workflow_factory_module_provider() is b


class TestGetNotificationsModuleProvider:
    """get_notifications_module_provider — notifications module."""

    def test_override_returns_sentinel(self) -> None:
        sentinel = object()
        set_notifications_module_provider(sentinel)
        assert get_notifications_module_provider() is sentinel

    def test_overrides_dict_short_circuits(self) -> None:
        sentinel = object()
        mod._overrides["notifications_module"] = sentinel
        result = get_notifications_module_provider()
        assert result is sentinel

    def test_no_override_calls_resolve_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"yes": False}

        def fake_resolve(name: str) -> Any:
            assert name == "notifications"
            called["yes"] = True
            return MagicMock(name="notifications_module")

        monkeypatch.setattr(mod, "resolve_module", fake_resolve)
        result = get_notifications_module_provider()
        assert called["yes"] is True
        assert result is not None


class TestSetNotificationsModuleProvider:
    """set_notifications_module_provider — test-override."""

    def test_persists_value(self) -> None:
        sentinel = object()
        set_notifications_module_provider(sentinel)
        assert get_notifications_module_provider() is sentinel

    def test_overwrites_previous(self) -> None:
        a = object()
        b = object()
        set_notifications_module_provider(a)
        set_notifications_module_provider(b)
        assert get_notifications_module_provider() is b


class TestOverridesIsolation:
    """Каждый домен (workflow_factory, notifications) имеет свой ключ в _overrides."""

    def test_keys_are_separate(self) -> None:
        wf_sentinel = object()
        notif_sentinel = object()
        set_workflow_factory_module_provider(wf_sentinel)
        set_notifications_module_provider(notif_sentinel)

        # Каждый get возвращает свой sentinel
        assert get_workflow_factory_module_provider() is wf_sentinel
        assert get_notifications_module_provider() is notif_sentinel

    def test_clearing_one_does_not_affect_other(self) -> None:
        wf_sentinel = object()
        notif_sentinel = object()
        set_workflow_factory_module_provider(wf_sentinel)
        set_notifications_module_provider(notif_sentinel)

        # Очистим только workflow_factory
        del mod._overrides["workflow_factory_module"]

        # notifications — всё ещё в overrides
        assert "notifications_module" in mod._overrides
        assert get_notifications_module_provider() is notif_sentinel


class TestRegisterCalledAtImport:
    """register(_overrides) вызывается при импорте модуля."""

    def test_register_call_during_import(self) -> None:
        # _overrides уже зарегистрирован в store (через register())
        from src.backend.core.di.providers.workflow import _overrides_store

        # _domains — list of registered _overrides dicts
        # После import _notifications.py, _overrides_store._domains содержит mod._overrides
        assert len(_overrides_store._domains) > 0
        # mod._overrides должен быть среди зарегистрированных
        assert mod._overrides in _overrides_store._domains

    def test_overrides_dict_present_in_store(self) -> None:
        from src.backend.core.di.providers.workflow import _overrides_store

        # mod._overrides должен быть среди зарегистрированных
        assert mod._overrides in _overrides_store._domains


class TestModuleImport:
    """Smoke import."""

    def test_module_imports(self) -> None:
        from src.backend.core.di.providers.workflow import _notifications as m

        assert m is mod

    def test_overrides_dict_initialized(self) -> None:
        assert isinstance(mod._overrides, dict)

    def test_functions_callable(self) -> None:
        assert callable(get_workflow_factory_module_provider)
        assert callable(set_workflow_factory_module_provider)
        assert callable(get_notifications_module_provider)
        assert callable(set_notifications_module_provider)


class TestResolveModuleBranch:
    """Без override — get_*_module_provider вызывает resolve_module."""

    def test_workflow_factory_resolve_called_with_correct_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_name = {"name": None}

        def fake_resolve(name: str) -> Any:
            captured_name["name"] = name
            return MagicMock()

        monkeypatch.setattr(mod, "resolve_module", fake_resolve)
        get_workflow_factory_module_provider()
        # R1 fix: ключ "workflow.factory", без .factory suffix в INFRA_MODULES
        assert captured_name["name"] == "workflow.factory"

    def test_notifications_resolve_called_with_correct_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured_name = {"name": None}

        def fake_resolve(name: str) -> Any:
            captured_name["name"] = name
            return MagicMock()

        monkeypatch.setattr(mod, "resolve_module", fake_resolve)
        get_notifications_module_provider()
        assert captured_name["name"] == "notifications"