"""Tests for ``src.backend.core.di.providers.scheduler``.

S170 NEW (Milestone 1) — scheduler domain provider.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.di.providers import scheduler as mod
from src.backend.core.di.providers.scheduler import (
    get_scheduler_provider,
    set_scheduler_provider,
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    mod._overrides.clear()
    yield
    mod._overrides.clear()


class TestGetSchedulerProvider:
    """get_scheduler_provider() — singleton + override."""

    def test_override_returns_sentinel(self) -> None:
        sentinel = object()
        set_scheduler_provider(sentinel)
        assert get_scheduler_provider() is sentinel

    def test_overrides_dict_short_circuits(self) -> None:
        sentinel = object()
        mod._overrides["scheduler"] = sentinel
        assert get_scheduler_provider() is sentinel

    def test_no_override_calls_resolve_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"yes": False, "name": None}

        def fake_resolve(name: str) -> Any:
            called["yes"] = True
            called["name"] = name
            return MagicMock()

        monkeypatch.setattr(mod, "resolve_module", fake_resolve)
        result = get_scheduler_provider()
        assert called["yes"] is True
        assert called["name"] == "scheduler.scheduler_manager"
        # Возвращает .get_default_scheduler() от resolved module
        assert result is not None


class TestSetSchedulerProvider:
    """set_scheduler_provider() — test-инжекция."""

    def test_persists_value(self) -> None:
        sentinel = object()
        set_scheduler_provider(sentinel)
        assert get_scheduler_provider() is sentinel

    def test_overrides_previous(self) -> None:
        a = object()
        b = object()
        set_scheduler_provider(a)
        set_scheduler_provider(b)
        assert get_scheduler_provider() is b


class TestModuleExports:
    """__all__ проверка."""

    def test_exports_two_functions(self) -> None:
        assert "get_scheduler_provider" in mod.__all__
        assert "set_scheduler_provider" in mod.__all__
        assert len(mod.__all__) == 2

    def test_functions_callable(self) -> None:
        assert callable(get_scheduler_provider)
        assert callable(set_scheduler_provider)

    def test_module_imports(self) -> None:
        from src.backend.core.di.providers import scheduler as m

        assert m is mod

    def test_overrides_dict_initialized(self) -> None:
        assert isinstance(mod._overrides, dict)


class TestGetDefaultScheduler:
    """resolve_module возвращает модуль с .get_default_scheduler()."""

    def test_uses_get_default_scheduler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        mock_module = MagicMock()
        mock_module.get_default_scheduler.return_value = sentinel
        monkeypatch.setattr(mod, "resolve_module", lambda _: mock_module)
        result = get_scheduler_provider()
        assert result is sentinel
        mock_module.get_default_scheduler.assert_called_once_with()