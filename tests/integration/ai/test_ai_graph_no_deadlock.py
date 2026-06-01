"""Integration test для Block 2.2 (gap-ai-2.2, ADR-0073).

Проверяет что :func:`_make_action_tool` возвращает async-only ``StructuredTool``
без sync-deadlock-path (``_sync_run`` с ``asyncio.run`` + ``ThreadPoolExecutor``).

Сценарий регрессии до Block 2.2:
    При работающем event loop ``_sync_run`` вызывал ``asyncio.run`` внутри
    ``ThreadPoolExecutor.submit(...)`` — это создавало вложенный loop в worker-
    потоке. На пуле shared connections (DB / Redis) это давало deadlock
    либо ``RuntimeError: asyncio.run() cannot be called from a running event loop``
    под нагрузкой (20+ parallel agent runs через ``asyncio.gather``).

Сценарий после Block 2.2:
    ``StructuredTool.from_function(coroutine=_run_action, ...)`` без ``func=...``.
    LangGraph всегда async-path → tool.ainvoke / tool.coroutine.
    Sync-вызов либо генерируется LangChain через ``run_coroutine_threadsafe``,
    либо явно отвергается с понятной ошибкой.

Тест НЕ требует установленных langgraph / langchain_litellm — изолирован
через подмену ``action_handler_registry.dispatch`` и проверку атрибутов
``StructuredTool``.
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture()
def langchain_core_available() -> bool:
    """Skip test если langchain_core не установлен."""
    try:
        importlib.import_module("langchain_core.tools")
        return True
    except ImportError:
        return False


def test_make_action_tool_returns_async_only_tool(
    monkeypatch: pytest.MonkeyPatch, langchain_core_available: bool
) -> None:
    """``_make_action_tool`` возвращает StructuredTool с coroutine, без sync-func deadlock-pattern."""
    if not langchain_core_available:
        pytest.skip("langchain_core не установлен — пропуск integration теста")

    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.services.ai.ai_graph import _make_action_tool

    async def _fake_dispatch(cmd: Any) -> dict[str, str]:
        return {"status": "ok", "action": cmd.action}

    monkeypatch.setattr(action_handler_registry, "dispatch", _fake_dispatch)

    tool = _make_action_tool("test.action")
    assert tool.name == "test_action"
    assert tool.coroutine is not None, (
        "StructuredTool должен иметь coroutine для async-path LangGraph"
    )

    # Block 2.2 enforcement: sync-функция НЕ должна содержать asyncio.run()
    # внутри ThreadPoolExecutor — это deadlock pattern.
    # При async-only tool tool.func может быть None или auto-generated wrapper,
    # но ни в коем случае не _sync_run с asyncio.run.
    import inspect

    if tool.func is not None and not inspect.iscoroutinefunction(tool.func):
        # Если LangChain сгенерировал sync-wrapper — он не должен звать asyncio.run.
        source = inspect.getsource(tool.func) if hasattr(tool.func, "__code__") else ""
        assert "asyncio.run(" not in source, (
            "tool.func содержит asyncio.run — deadlock-pattern Block 2.2"
        )


@pytest.mark.asyncio
async def test_action_tool_ainvoke_in_running_loop(
    monkeypatch: pytest.MonkeyPatch, langchain_core_available: bool
) -> None:
    """tool.ainvoke работает внутри running event loop без RuntimeError."""
    if not langchain_core_available:
        pytest.skip("langchain_core не установлен — пропуск integration теста")

    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.services.ai.ai_graph import _make_action_tool

    dispatch_mock = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(action_handler_registry, "dispatch", dispatch_mock)

    tool = _make_action_tool("test.action_in_loop")
    result = await tool.ainvoke({"param": "value"})
    assert result is not None
    dispatch_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_deadlock_under_parallel_load(
    monkeypatch: pytest.MonkeyPatch, langchain_core_available: bool
) -> None:
    """20 parallel tool.ainvoke завершаются без RuntimeError / deadlock."""
    if not langchain_core_available:
        pytest.skip("langchain_core не установлен — пропуск integration теста")

    from src.backend.dsl.commands.registry import action_handler_registry
    from src.backend.services.ai.ai_graph import _make_action_tool

    counter = {"n": 0}

    async def _slow_dispatch(cmd: Any) -> dict[str, int]:
        await asyncio.sleep(0.01)
        counter["n"] += 1
        return {"n": counter["n"]}

    monkeypatch.setattr(action_handler_registry, "dispatch", _slow_dispatch)

    tool = _make_action_tool("test.parallel")
    results = await asyncio.wait_for(
        asyncio.gather(*[tool.ainvoke({"i": i}) for i in range(20)]),
        timeout=10.0,
    )
    assert len(results) == 20
    assert counter["n"] == 20
