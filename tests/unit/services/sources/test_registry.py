"""Unit tests for src.backend.services.sources.registry."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from src.backend.core.di.app_state import reset_app_state
from src.backend.core.interfaces.source import SourceKind
from src.backend.services.sources.registry import (
    SinkRegistry,
    SourceRegistry,
    get_sink_registry,
    get_source_registry,
)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    reset_app_state()
    yield
    reset_app_state()


def _fake_source(source_id: str, kind: SourceKind = SourceKind.HTTP) -> MagicMock:
    source = MagicMock()
    source.source_id = source_id
    source.kind = kind
    source.start = MagicMock()
    source.stop = MagicMock()
    source.health = MagicMock()
    return source


def _fake_sink(sink_id: str, kind: SourceKind = SourceKind.HTTP) -> MagicMock:
    sink = MagicMock()
    sink.sink_id = sink_id
    sink.kind = kind
    return sink


class TestSourceRegistry:
    def test_register_and_get(self) -> None:
        reg = SourceRegistry()
        s = _fake_source("wh-1")
        reg.register(s)
        assert reg.get("wh-1") is s

    def test_register_duplicate_raises(self) -> None:
        reg = SourceRegistry()
        s = _fake_source("wh-1")
        reg.register(s)
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            reg.register(s)

    def test_get_missing_raises(self) -> None:
        reg = SourceRegistry()
        with pytest.raises(KeyError, match="не зарегистрирован"):
            reg.get("missing")

    def test_all_sorted(self) -> None:
        reg = SourceRegistry()
        s1 = _fake_source("b")
        s2 = _fake_source("a")
        reg.register(s1)
        reg.register(s2)
        assert reg.all() == (s2, s1)

    def test_len_and_contains(self) -> None:
        reg = SourceRegistry()
        s = _fake_source("x")
        assert len(reg) == 0
        assert "x" not in reg
        reg.register(s)
        assert len(reg) == 1
        assert "x" in reg
        assert 123 not in reg


class TestSinkRegistry:
    def test_register_and_get(self) -> None:
        reg = SinkRegistry()
        s = _fake_sink("sk-1")
        reg.register(s)
        assert reg.get("sk-1") is s

    def test_register_duplicate_raises(self) -> None:
        reg = SinkRegistry()
        s = _fake_sink("sk-1")
        reg.register(s)
        with pytest.raises(ValueError, match="уже зарегистрирован"):
            reg.register(s)

    def test_get_missing_raises(self) -> None:
        reg = SinkRegistry()
        with pytest.raises(KeyError, match="не зарегистрирован"):
            reg.get("missing")

    def test_all_sorted(self) -> None:
        reg = SinkRegistry()
        s1 = _fake_sink("b")
        s2 = _fake_sink("a")
        reg.register(s1)
        reg.register(s2)
        assert reg.all() == (s2, s1)

    def test_len_and_contains(self) -> None:
        reg = SinkRegistry()
        s = _fake_sink("y")
        assert len(reg) == 0
        assert "y" not in reg
        reg.register(s)
        assert len(reg) == 1
        assert "y" in reg


class TestGetRegistry:
    def test_get_source_registry_factory(self) -> None:
        reg = get_source_registry()
        assert isinstance(reg, SourceRegistry)
        # cached
        assert get_source_registry() is reg

    def test_get_sink_registry_factory(self) -> None:
        reg = get_sink_registry()
        assert isinstance(reg, SinkRegistry)
        assert get_sink_registry() is reg
