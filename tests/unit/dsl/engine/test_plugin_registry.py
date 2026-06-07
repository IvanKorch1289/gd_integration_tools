"""Unit tests for ProcessorPluginRegistry (legacy shim)."""

# ruff: noqa: S101

from __future__ import annotations

import warnings
from typing import Any

import pytest

from src.backend.dsl.engine.plugin_registry import (
    ProcessorPluginRegistry,
    get_processor_plugin_registry,
)
from src.backend.dsl.engine.processors.base import BaseProcessor


class DummyProcessor(BaseProcessor):
    def __init__(self, x: int = 0) -> None:
        super().__init__()
        self.x = x

    async def process(self, exchange: Any, context: Any) -> None: ...


def test_register_class() -> None:
    reg = ProcessorPluginRegistry()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        reg.register_class("dummy", DummyProcessor)
    assert reg.is_registered("dummy")
    assert reg.get("dummy") is DummyProcessor


def test_register_dotted_path() -> None:
    reg = ProcessorPluginRegistry()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        reg.register(
            "dummy", "tests.unit.dsl.engine.test_plugin_registry.DummyProcessor"
        )
    assert reg.get("dummy").__name__ == "DummyProcessor"


def test_register_invalid_type_raises() -> None:
    reg = ProcessorPluginRegistry()
    with pytest.raises(TypeError, match="not a BaseProcessor subclass"):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            reg.register("bad", "builtins.str")


def test_get_missing_returns_none() -> None:
    reg = ProcessorPluginRegistry()
    assert reg.get("missing") is None


def test_create_instance() -> None:
    reg = ProcessorPluginRegistry()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        reg.register_class("dummy", DummyProcessor)
    inst = reg.create("dummy", x=5)
    assert isinstance(inst, DummyProcessor)
    assert inst.x == 5


def test_create_missing_raises() -> None:
    reg = ProcessorPluginRegistry()
    with pytest.raises(KeyError, match="not registered"):
        reg.create("missing")


def test_list_plugins() -> None:
    reg = ProcessorPluginRegistry()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        reg.register_class("a", DummyProcessor)
        reg.register_class("b", DummyProcessor)
    plugins = reg.list_plugins()
    assert plugins == {"a": "DummyProcessor", "b": "DummyProcessor"}


def test_get_processor_plugin_registry_singleton() -> None:
    r1 = get_processor_plugin_registry()
    r2 = get_processor_plugin_registry()
    assert r1 is r2
