"""Sprint 7 Team T5 — unit-тесты hot_swap API.

Покрывает:
    1. hot_swap(unknown_plugin) → HotSwapError.
    2. hot_swap успешно вызывает loader.shutdown_all + discover_and_load.
    3. Module reload через importlib.reload вызывается при загруженном плагине.
    4. hot_swap возвращает HotSwapResult со status="reloaded".
    5. hot_swap фиксирует "failed", если после reload плагин не в loaded-статусе.
    6. HotSwapResult.to_dict() сериализует все поля.
    7. shutdown_all-падение оборачивается в HotSwapError.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from typing import Any

import pytest

from src.backend.core.plugin_runtime.hot_swap import (
    HotSwapError,
    HotSwapResult,
    hot_swap,
)


@dataclass
class _FakeEntry:
    """Минимальная имитация LoadedPlugin для unit-тестов."""

    name: str
    version: str = "1.0.0"
    status: str = "loaded"
    instance: Any = None
    manifest: Any = None
    reason: str | None = None


class _FakeLoader:
    """Имитация PluginLoader для unit-тестов.

    Возвращает заранее подготовленные entries, считает количество
    вызовов shutdown_all + discover_and_load.
    """

    def __init__(
        self,
        *,
        entries_before: list[_FakeEntry] | None = None,
        entries_after: list[_FakeEntry] | None = None,
        shutdown_raises: Exception | None = None,
        discover_raises: Exception | None = None,
    ) -> None:
        self._entries_before = entries_before or []
        self._entries_after = (
            entries_after if entries_after is not None else entries_before or []
        )
        self._loaded_dict: dict[str, _FakeEntry] = {
            e.name: e for e in self._entries_before
        }
        self._owners: dict[str, dict[str, str]] = {"actions": {"example.echo": "x"}}
        self._shutdown_raises = shutdown_raises
        self._discover_raises = discover_raises
        self.shutdown_calls = 0
        self.discover_calls = 0
        # Для удобства — какие entries отдавать после discover_and_load.
        self._next_after = self._entries_after

    @property
    def loaded(self) -> tuple[_FakeEntry, ...]:
        return tuple(self._loaded_dict.values())

    @property
    def _loaded(self) -> dict[str, _FakeEntry]:
        return self._loaded_dict

    async def shutdown_all(self) -> None:
        self.shutdown_calls += 1
        if self._shutdown_raises:
            raise self._shutdown_raises

    async def discover_and_load(self) -> tuple[_FakeEntry, ...]:
        self.discover_calls += 1
        if self._discover_raises:
            raise self._discover_raises
        # Эмулируем re-discovery: подкладываем entries_after.
        self._loaded_dict = {e.name: e for e in self._next_after}
        return self.loaded


@pytest.mark.asyncio
async def test_hot_swap_raises_if_plugin_unknown() -> None:
    """hot_swap(unknown_plugin) → HotSwapError."""
    loader = _FakeLoader(entries_before=[])
    with pytest.raises(HotSwapError) as excinfo:
        await hot_swap("missing", loader)  # type: ignore[arg-type]
    assert "not registered" in str(excinfo.value)


@pytest.mark.asyncio
async def test_hot_swap_calls_shutdown_and_discover() -> None:
    """Успешный hot_swap вызывает shutdown_all + discover_and_load."""
    entry_before = _FakeEntry(name="example_plugin", version="1.0.0")
    entry_after = _FakeEntry(name="example_plugin", version="1.0.1")
    loader = _FakeLoader(entries_before=[entry_before], entries_after=[entry_after])
    result = await hot_swap("example_plugin", loader)  # type: ignore[arg-type]
    assert loader.shutdown_calls == 1
    assert loader.discover_calls == 1
    assert result.status == "reloaded"


@pytest.mark.asyncio
async def test_hot_swap_returns_versions() -> None:
    """HotSwapResult содержит old_version + new_version."""
    entry_before = _FakeEntry(name="p", version="1.0.0")
    entry_after = _FakeEntry(name="p", version="2.0.0")
    loader = _FakeLoader(entries_before=[entry_before], entries_after=[entry_after])
    result = await hot_swap("p", loader)  # type: ignore[arg-type]
    assert result.old_version == "1.0.0"
    assert result.new_version == "2.0.0"


@pytest.mark.asyncio
async def test_hot_swap_failed_if_not_rediscovered() -> None:
    """Если после reload плагина нет в loader.loaded — status='failed'."""
    entry_before = _FakeEntry(name="p", version="1.0.0")
    loader = _FakeLoader(
        entries_before=[entry_before],
        entries_after=[],  # после reload плагин исчез
    )
    result = await hot_swap("p", loader)  # type: ignore[arg-type]
    assert result.status == "failed"
    assert result.reason and "rediscovered" in result.reason


@pytest.mark.asyncio
async def test_hot_swap_failed_if_capability_denied() -> None:
    """Если плагин после reload в status='failed' — это пробрасывается."""
    entry_before = _FakeEntry(name="p", version="1.0.0", status="loaded")
    entry_after = _FakeEntry(
        name="p",
        version="1.0.0",
        status="failed",
        reason="capability_error: mq.publish.* not allocated",
    )
    loader = _FakeLoader(entries_before=[entry_before], entries_after=[entry_after])
    result = await hot_swap("p", loader)  # type: ignore[arg-type]
    assert result.status == "failed"
    assert result.reason and "capability_error" in result.reason


@pytest.mark.asyncio
async def test_hot_swap_wraps_shutdown_failure() -> None:
    """Падение shutdown_all оборачивается в HotSwapError."""
    entry_before = _FakeEntry(name="p", version="1.0.0")
    loader = _FakeLoader(
        entries_before=[entry_before], shutdown_raises=RuntimeError("boom")
    )
    with pytest.raises(HotSwapError) as excinfo:
        await hot_swap("p", loader)  # type: ignore[arg-type]
    assert "shutdown_all_failed" in str(excinfo.value)


@pytest.mark.asyncio
async def test_hot_swap_wraps_discover_failure() -> None:
    """Падение discover_and_load оборачивается в HotSwapError."""
    entry_before = _FakeEntry(name="p", version="1.0.0")
    loader = _FakeLoader(
        entries_before=[entry_before], discover_raises=RuntimeError("scan failed")
    )
    with pytest.raises(HotSwapError) as excinfo:
        await hot_swap("p", loader)  # type: ignore[arg-type]
    assert "discover_and_load_failed" in str(excinfo.value)


def test_hot_swap_result_to_dict() -> None:
    """HotSwapResult.to_dict сериализует все 5 полей."""
    res = HotSwapResult(
        plugin_name="p",
        old_version="1.0.0",
        new_version="1.0.1",
        status="reloaded",
        reason=None,
    )
    payload = res.to_dict()
    assert payload == {
        "plugin_name": "p",
        "old_version": "1.0.0",
        "new_version": "1.0.1",
        "status": "reloaded",
        "reason": None,
    }


@pytest.mark.asyncio
async def test_hot_swap_reloads_module() -> None:
    """importlib.reload вызывается, если у плагина есть instance с __module__."""
    # Подкладываем фейковый модуль в sys.modules.
    fake_module = types.ModuleType("tests_unit_hot_swap_fake_mod")
    fake_module.reload_marker = 1  # type: ignore[attr-defined]
    sys.modules["tests_unit_hot_swap_fake_mod"] = fake_module

    class _FakePluginInstance:
        pass

    # Подменяем __module__, как будто класс импортирован из fake-модуля.
    _FakePluginInstance.__module__ = "tests_unit_hot_swap_fake_mod"
    instance = _FakePluginInstance()

    entry_before = _FakeEntry(name="p", version="1.0.0", instance=instance)
    entry_after = _FakeEntry(name="p", version="1.0.1")
    loader = _FakeLoader(entries_before=[entry_before], entries_after=[entry_after])

    try:
        result = await hot_swap("p", loader)  # type: ignore[arg-type]
        assert result.status == "reloaded"
    finally:
        sys.modules.pop("tests_unit_hot_swap_fake_mod", None)
