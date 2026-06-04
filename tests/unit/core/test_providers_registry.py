"""Tests for src.backend.core.providers_registry."""

from __future__ import annotations

import pytest

from src.backend.core import providers_registry as reg


class TestProvidersRegistry:
    def setup_method(self) -> None:
        reg.clear_registry()

    def test_register_and_get(self) -> None:
        obj = object()
        reg.register_provider("llm", "ollama", obj)
        assert reg.get_provider("llm", "ollama") is obj

    def test_get_missing_raises(self) -> None:
        with pytest.raises(KeyError):
            reg.get_provider("llm", "missing")

    def test_list_providers(self) -> None:
        reg.register_provider("llm", "a", 1)
        reg.register_provider("llm", "b", 2)
        assert reg.list_providers("llm") == {"llm": ["a", "b"]}

    def test_list_all(self) -> None:
        reg.register_provider("cat1", "a", 1)
        reg.register_provider("cat2", "b", 2)
        assert reg.list_providers() == {"cat1": ["a"], "cat2": ["b"]}

    def test_unregister_and_clear(self) -> None:
        reg.register_provider("x", "y", 1)
        reg.unregister_provider("x", "y")
        with pytest.raises(KeyError):
            reg.get_provider("x", "y")
        reg.register_provider("x", "z", 2)
        reg.clear_registry()
        assert reg.list_providers() == {}
