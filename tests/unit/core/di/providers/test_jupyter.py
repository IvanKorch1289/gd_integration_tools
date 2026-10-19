"""Tests for ``src.backend.core.di.providers.jupyter``.

S93 W1 C6: NotebookExecutionService singleton provider с test-override
и late import для избежания циркуляра.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.di.providers import jupyter as jupyter_mod
from src.backend.core.di.providers.jupyter import (
    get_notebook_execution_service_provider,
    reset_notebook_execution_service_overrides,
    set_notebook_execution_service_provider,
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    """Гарантируем чистый _overrides между тестами."""
    jupyter_mod._overrides.clear()
    yield
    jupyter_mod._overrides.clear()


class TestGetNotebookExecutionServiceProvider:
    """Override-ветка приоритетна над singleton-созданием."""

    def test_returns_override_value(self) -> None:
        sentinel = object()
        set_notebook_execution_service_provider(sentinel)
        assert get_notebook_execution_service_provider() is sentinel

    def test_overrides_dict_short_circuits(self) -> None:
        sentinel = object()
        jupyter_mod._overrides["notebook_execution_service"] = sentinel
        # Singleton-создание не должно вызываться
        result = get_notebook_execution_service_provider()
        assert result is sentinel

    def test_setter_persists(self) -> None:
        sentinel = object()
        set_notebook_execution_service_provider(sentinel)
        # Повторный get возвращает то же значение
        assert get_notebook_execution_service_provider() is sentinel

    def test_repeated_setter_overrides(self) -> None:
        a = object()
        b = object()
        set_notebook_execution_service_provider(a)
        assert get_notebook_execution_service_provider() is a
        set_notebook_execution_service_provider(b)
        assert get_notebook_execution_service_provider() is b


class TestResetOverrides:
    """reset_notebook_execution_service_overrides() — test-helper."""

    def test_clears_overrides(self) -> None:
        jupyter_mod._overrides["foo"] = "bar"
        jupyter_mod._overrides["baz"] = "qux"
        reset_notebook_execution_service_overrides()
        assert jupyter_mod._overrides == {}

    def test_clears_overrides_after_setter(self) -> None:
        set_notebook_execution_service_provider(object())
        assert "notebook_execution_service" in jupyter_mod._overrides
        reset_notebook_execution_service_overrides()
        assert jupyter_mod._overrides == {}


class TestLateImport:
    """Без override — провайдер делает late import и singleton-кеширует."""

    def test_no_override_triggers_singleton_creation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Без override: идём в ветку resolve_module/late-import
        # Подменяем Config и NotebookExecutionService
        sentinel_instance = object()
        captured: dict[str, Any] = {}

        class FakeSettings:
            pass

        class FakeService:
            def __init__(self, settings: Any) -> None:
                captured["settings"] = settings
                self._settings = settings

        # Подменяем модули на уровне sys.modules, чтобы late import подхватил их
        import sys
        import types

        fake_jupyter_hub = types.ModuleType(
            "src.backend.core.config.services.jupyter_hub"
        )
        fake_jupyter_hub.jupyter_hub_settings = FakeSettings()
        monkeypatch.setitem(
            sys.modules,
            "src.backend.core.config.services.jupyter_hub",
            fake_jupyter_hub,
        )

        fake_exec_svc_module = types.ModuleType(
            "src.backend.services.jupyter.execution_service"
        )
        fake_exec_svc_module.NotebookExecutionService = FakeService
        monkeypatch.setitem(
            sys.modules,
            "src.backend.services.jupyter.execution_service",
            fake_exec_svc_module,
        )

        result = get_notebook_execution_service_provider()
        # Singleton должен сохраниться в _overrides
        assert "notebook_execution_service" in jupyter_mod._overrides
        assert result is jupyter_mod._overrides["notebook_execution_service"]
        # Settings передан в конструктор
        assert isinstance(captured.get("settings"), FakeSettings)

    def test_singleton_cached_after_first_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # После первого вызова get — singleton в _overrides, повторный вызов
        # не должен создавать новый объект
        import sys
        import types

        class FakeSettings:
            pass

        class FakeService:
            instances: list[Any] = []

            def __init__(self, settings: Any) -> None:
                self._settings = settings
                FakeService.instances.append(self)

        fake_jupyter_hub = types.ModuleType(
            "src.backend.core.config.services.jupyter_hub"
        )
        fake_jupyter_hub.jupyter_hub_settings = FakeSettings()
        monkeypatch.setitem(
            sys.modules,
            "src.backend.core.config.services.jupyter_hub",
            fake_jupyter_hub,
        )
        fake_exec_svc = types.ModuleType(
            "src.backend.services.jupyter.execution_service"
        )
        fake_exec_svc.NotebookExecutionService = FakeService
        monkeypatch.setitem(
            sys.modules,
            "src.backend.services.jupyter.execution_service",
            fake_exec_svc,
        )

        first = get_notebook_execution_service_provider()
        second = get_notebook_execution_service_provider()
        # Только один экземпляр создан
        assert len(FakeService.instances) == 1
        assert first is second


class TestModuleExports:
    """Проверка экспортируемых символов модуля."""

    def test_getter_is_callable(self) -> None:
        assert callable(get_notebook_execution_service_provider)

    def test_setter_is_callable(self) -> None:
        assert callable(set_notebook_execution_service_provider)

    def test_reset_is_callable(self) -> None:
        assert callable(reset_notebook_execution_service_overrides)

    def test_module_imports(self) -> None:
        # Smoke: модуль загружается без ошибок
        from src.backend.core.di.providers import jupyter as _mod

        assert _mod is jupyter_mod

    def test_overrides_dict_initialized(self) -> None:
        # _overrides — пустой dict на старте модуля
        assert isinstance(jupyter_mod._overrides, dict)