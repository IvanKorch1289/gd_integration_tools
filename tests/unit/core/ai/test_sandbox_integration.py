"""Tests for S166 W2 sandbox integration in AIGateway."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.ai.sandbox import SandboxResult


@pytest.mark.asyncio
async def test_run_agent_code_uses_attached_sandbox() -> None:
    """S166 W2: attached sandbox.run() is called."""
    from src.backend.core.ai.gateway import AIGateway

    mock_sandbox = AsyncMock()
    mock_sandbox.run = AsyncMock(
        return_value=SandboxResult(stdout="ok", stderr="", exit_code=0, artifacts={})
    )
    gateway = AIGateway()
    gateway.attach_sandbox(mock_sandbox)

    result = await gateway.run_agent_code("print('hello')", timeout_seconds=5.0)
    assert result.stdout == "ok"
    mock_sandbox.run.assert_called_once_with("print('hello')", timeout_s=5.0)


@pytest.mark.asyncio
async def test_run_agent_code_fallback_to_noop_raises() -> None:
    """S166 W2: without attached sandbox, NoOpSandbox raises RuntimeError
    (explicit refusal to execute in main loop per V15 R-V15-4).
    """
    from src.backend.core.ai.gateway import AIGateway

    gateway = AIGateway()
    # No attach_sandbox call — should use NoOpSandbox which raises
    # RuntimeError to refuse unsafe code execution.
    with pytest.raises(RuntimeError, match="CodeSandbox не сконфигурирован"):
        await gateway.run_agent_code("print('hello')", timeout_seconds=1.0)


def test_attach_sandbox_stores_attribute() -> None:
    """S166 W2: attach_sandbox stores sandbox for later use."""
    from src.backend.core.ai.gateway import AIGateway

    gateway = AIGateway()
    mock_sandbox = object()
    gateway.attach_sandbox(mock_sandbox)
    assert gateway._sandbox is mock_sandbox