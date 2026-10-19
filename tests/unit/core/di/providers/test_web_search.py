"""Tests for ``src.backend.core.di.providers.web_search``.

S170 NEW (Milestone 1) — web search domain provider.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.di.providers import web_search as mod
from src.backend.core.di.providers.web_search import (
    get_web_search_provider,
    set_web_search_provider,
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> None:
    mod._overrides.clear()
    yield
    mod._overrides.clear()


class TestGetWebSearchProvider:
    """get_web_search_provider() — singleton + override."""

    def test_override_returns_sentinel(self) -> None:
        sentinel = object()
        set_web_search_provider(sentinel)
        assert get_web_search_provider() is sentinel

    def test_overrides_dict_short_circuits(self) -> None:
        sentinel = object()
        mod._overrides["web_search"] = sentinel
        assert get_web_search_provider() is sentinel

    def test_no_override_calls_resolve_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"yes": False, "name": None}

        def fake_resolve(name: str) -> Any:
            called["yes"] = True
            called["name"] = name
            return MagicMock()

        monkeypatch.setattr(mod, "resolve_module", fake_resolve)
        result = get_web_search_provider()
        assert called["yes"] is True
        assert called["name"] == "infrastructure.clients.external.search_providers"
        assert result is not None


class TestSetWebSearchProvider:
    """set_web_search_provider() — test-инжекция."""

    def test_persists_value(self) -> None:
        sentinel = object()
        set_web_search_provider(sentinel)
        assert get_web_search_provider() is sentinel

    def test_overrides_previous(self) -> None:
        a = object()
        b = object()
        set_web_search_provider(a)
        set_web_search_provider(b)
        assert get_web_search_provider() is b


class TestGetDefault:
    """resolve_module возвращает модуль с .get_default()."""

    def test_uses_get_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sentinel = object()
        mock_module = MagicMock()
        mock_module.get_default.return_value = sentinel
        monkeypatch.setattr(mod, "resolve_module", lambda _: mock_module)
        result = get_web_search_provider()
        assert result is sentinel
        mock_module.get_default.assert_called_once_with()


class TestModuleExports:
    """__all__ проверка."""

    def test_exports_two_functions(self) -> None:
        assert "get_web_search_provider" in mod.__all__
        assert "set_web_search_provider" in mod.__all__
        assert len(mod.__all__) == 2

    def test_functions_callable(self) -> None:
        assert callable(get_web_search_provider)
        assert callable(set_web_search_provider)

    def test_module_imports(self) -> None:
        from src.backend.core.di.providers import web_search as m

        assert m is mod

    def test_overrides_dict_initialized(self) -> None:
        assert isinstance(mod._overrides, dict)