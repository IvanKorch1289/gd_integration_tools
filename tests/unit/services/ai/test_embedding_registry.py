"""Тесты EmbeddingProviderRegistry: register/get/list."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.embedding_registry import EmbeddingProviderRegistry


def _make_provider(vectors: list[list[float]]) -> object:
    p = type("P", (), {})()
    p.embed = AsyncMock(return_value=vectors)
    return p


def test_register_and_get_returns_same_instance() -> None:
    registry = EmbeddingProviderRegistry()
    instance = _make_provider([[0.1]])
    registry.register("test", lambda: instance)
    got = registry.get("test")
    assert got is instance


def test_get_unknown_raises_keyerror() -> None:
    registry = EmbeddingProviderRegistry()
    with pytest.raises(KeyError):
        registry.get("missing")


def test_register_overwrites() -> None:
    registry = EmbeddingProviderRegistry()
    a = _make_provider([[1.0]])
    b = _make_provider([[2.0]])
    registry.register("p", lambda: a)
    registry.register("p", lambda: b)
    assert registry.get("p") is b


def test_list_returns_sorted_names() -> None:
    registry = EmbeddingProviderRegistry()
    registry.register("z", lambda: _make_provider([]))
    registry.register("a", lambda: _make_provider([]))
    assert registry.list() == ["a", "z"]


def test_factory_singleton_caches_instance() -> None:
    registry = EmbeddingProviderRegistry()
    calls = {"n": 0}

    def factory() -> object:
        calls["n"] += 1
        return _make_provider([])

    registry.register("p", factory)
    registry.get("p")
    registry.get("p")
    assert calls["n"] == 1
