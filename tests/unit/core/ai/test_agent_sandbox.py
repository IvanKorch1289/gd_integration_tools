"""Unit-тесты AgentSandbox (S133 W4).

Покрытие:
    * InProcessAgentSandbox делегирует build_and_run_agent.
    * ProcessPoolAgentSandbox запускает ReAct в spawn-воркере.
    * shutdown идемпотентен.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.services.ai.agent_sandbox import (
    InProcessAgentSandbox,
    ProcessPoolAgentSandbox,
)


@pytest.mark.asyncio
async def test_in_process_delegates_to_build_and_run_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """InProcess sandbox вызывает build_and_run_agent в текущем event loop."""
    calls: list[dict[str, Any]] = []

    async def _fake_build_and_run_agent(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"response": "ok-in-process"}

    monkeypatch.setattr(
        "src.backend.services.ai.ai_graph.build_and_run_agent",
        _fake_build_and_run_agent,
    )

    sandbox = InProcessAgentSandbox()
    result = await sandbox.run_react(
        prompt="hello",
        tool_actions=["a.b"],
        model="gpt-4o-mini",
        temperature=0.0,
        durable=False,
        session_id="sid-1",
    )

    assert result.success is True
    assert result.data == {"response": "ok-in-process"}
    assert result.backend == "in_process"
    assert calls[0]["prompt"] == "hello"
    assert calls[0]["tool_actions"] == ["a.b"]
    assert calls[0]["model"] == "gpt-4o-mini"
    assert calls[0]["session_id"] == "sid-1"


@pytest.mark.asyncio
async def test_in_process_reports_error() -> None:
    """Если build_and_run_agent вернул error — success=False."""
    sandbox = InProcessAgentSandbox()
    # build_and_run_agent недоступен в этом тесте (langgraph не установлен) —
    # ожидаем error-ответ.
    result = await sandbox.run_react(
        prompt="hello",
        tool_actions=[],
        model="gpt-4o-mini",
        temperature=0.0,
        durable=False,
        session_id=None,
    )
    assert result.success is False
    assert "error" in result.data


@pytest.mark.asyncio
async def test_process_pool_runs_in_subprocess() -> None:
    """ProcessPool sandbox выполняет ReAct в отдельном spawn-процессе."""
    sandbox = ProcessPoolAgentSandbox(max_workers=1)
    try:
        result = await sandbox.run_react(
            prompt="test prompt",
            tool_actions=[],
            model="gpt-4o-mini",
            temperature=0.0,
            durable=False,
            session_id="sid-2",
        )
        # LangGraph не установлен в тестовом окружении — ожидаем graceful error.
        assert result.backend == "process_pool"
        assert "error" in result.data
    finally:
        await sandbox.shutdown()


@pytest.mark.asyncio
async def test_process_pool_shutdown_idempotent() -> None:
    """shutdown можно вызывать несколько раз."""
    sandbox = ProcessPoolAgentSandbox(max_workers=1)
    await sandbox.shutdown()
    await sandbox.shutdown()
    assert sandbox._closed is True
