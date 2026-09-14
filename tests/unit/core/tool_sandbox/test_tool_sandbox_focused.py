"""Focused tests for ``core.tool_sandbox`` (Wave 3 #21)."""

from __future__ import annotations

import asyncio

import pytest

from src.backend.core.tool_sandbox import (
    SandboxConfig,
    SandboxedTool,
    SandboxMode,
    SandboxResult,
    ToolPolicyViolation,
    ToolSandbox,
)
from src.backend.core.tool_sandbox.sandbox import (
    get_default_sandbox,
    reset_default_sandbox,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_default_sandbox()


class TestSandboxMode:
    def test_values(self) -> None:
        assert SandboxMode.PERMISSIVE.value == "permissive"
        assert SandboxMode.ENFORCE.value == "enforce"
        assert SandboxMode.AUDIT.value == "audit"


class TestSandboxConfig:
    def test_defaults(self) -> None:
        c = SandboxConfig()
        assert c.max_cpu_seconds == 30.0
        assert c.max_memory_mb == 512
        assert c.allow_filesystem is True
        assert c.allow_network is True
        assert c.mode == SandboxMode.ENFORCE

    def test_full(self) -> None:
        c = SandboxConfig(
            max_cpu_seconds=5.0,
            max_memory_mb=128,
            allow_filesystem=False,
            allow_network=False,
            mode=SandboxMode.AUDIT,
        )
        assert c.max_cpu_seconds == 5.0
        assert c.allow_filesystem is False


class TestSandboxResult:
    def test_defaults(self) -> None:
        r = SandboxResult(value=42, success=True)
        assert r.value == 42
        assert r.duration_ms == 0.0
        assert r.error is None
        assert r.error_type is None
        assert r.policy_violations == []


class TestToolPolicyViolation:
    def test_init(self) -> None:
        e = ToolPolicyViolation("test msg", violation_type="timeout")
        assert e.violation_type == "timeout"
        assert "test msg" in str(e)

    def test_default_violation_type(self) -> None:
        e = ToolPolicyViolation("test")
        assert e.violation_type == "unknown"


class TestToolSandboxInit:
    def test_init_default(self) -> None:
        s = ToolSandbox()
        assert s.config is not None
        assert s.history() == []

    def test_init_with_config(self) -> None:
        cfg = SandboxConfig(max_cpu_seconds=5.0)
        s = ToolSandbox(config=cfg)
        assert s.config.max_cpu_seconds == 5.0


class TestToolSandboxConfigure:
    def test_configure(self) -> None:
        s = ToolSandbox()
        s.configure(max_cpu_seconds=10.0)
        assert s.config.max_cpu_seconds == 10.0


class TestToolSandboxWrap:
    def test_wrap_returns_sandboxed_tool(self) -> None:
        s = ToolSandbox()

        def my_tool(x: int) -> int:
            return x * 2

        wrapped = s.wrap(my_tool)
        assert isinstance(wrapped, SandboxedTool)
        assert wrapped.name == "my_tool"
        assert wrapped.func is my_tool

    def test_wrap_async(self) -> None:
        s = ToolSandbox()

        async def async_tool(x: int) -> int:
            return x + 1

        wrapped = s.wrap(async_tool)
        assert wrapped.func is async_tool


class TestToolSandboxExecuteSync:
    async def test_sync_tool_success(self) -> None:
        s = ToolSandbox()

        def double(x: int) -> int:
            return x * 2

        wrapped = s.wrap(double)
        result = await s.execute(wrapped, 5)
        assert result.success
        assert result.value == 10
        assert result.error is None

    async def test_sync_tool_exception(self) -> None:
        s = ToolSandbox()

        def fail_tool():
            raise ValueError("boom")

        wrapped = s.wrap(fail_tool)
        result = await s.execute(wrapped)
        assert result.success is False
        assert "ValueError" in result.error
        assert result.error_type == "ValueError"

    async def test_sync_tool_timeout(self) -> None:
        s = ToolSandbox(SandboxConfig(max_cpu_seconds=0.1))

        def slow_tool():
            import time
            time.sleep(1.0)
            return "done"

        wrapped = s.wrap(slow_tool)
        result = await s.execute(wrapped)
        assert result.success is False
        assert "Timeout" in result.error or "timeout" in result.error.lower()


class TestToolSandboxExecuteAsync:
    async def test_async_tool_success(self) -> None:
        s = ToolSandbox()

        async def double(x: int) -> int:
            return x * 2

        wrapped = s.wrap(double)
        result = await s.execute(wrapped, 5)
        assert result.success
        assert result.value == 10

    async def test_async_tool_timeout(self) -> None:
        s = ToolSandbox(SandboxConfig(max_cpu_seconds=0.1))

        async def slow():
            await asyncio.sleep(1.0)
            return "done"

        wrapped = s.wrap(slow)
        result = await s.execute(wrapped)
        assert result.success is False
        assert "Timeout" in result.error or "timeout" in result.error.lower()


class TestToolSandboxPolicy:
    async def test_network_blocked(self) -> None:
        s = ToolSandbox(
            SandboxConfig(allow_network=False, mode=SandboxMode.ENFORCE)
        )

        def fetch_url():
            return "data"

        wrapped = s.wrap(fetch_url)
        result = await s.execute(wrapped)
        assert result.success is False
        assert "network_access_denied" in result.policy_violations

    async def test_filesystem_blocked(self) -> None:
        s = ToolSandbox(
            SandboxConfig(allow_filesystem=False, mode=SandboxMode.ENFORCE)
        )

        def read_file():
            return "content"

        wrapped = s.wrap(read_file)
        result = await s.execute(wrapped)
        assert result.success is False
        assert "filesystem_access_denied" in result.policy_violations

    async def test_safe_tool_passes(self) -> None:
        s = ToolSandbox(
            SandboxConfig(allow_network=False, allow_filesystem=False)
        )

        def safe_compute(x: int) -> int:
            return x * 2

        wrapped = s.wrap(safe_compute)
        result = await s.execute(wrapped, 5)
        assert result.success
        assert result.value == 10


class TestToolSandboxHistory:
    async def test_history_accumulates(self) -> None:
        s = ToolSandbox()

        def t(x: int) -> int:
            return x

        wrapped = s.wrap(t)
        await s.execute(wrapped, 1)
        await s.execute(wrapped, 2)
        await s.execute(wrapped, 3)
        assert len(s.history()) == 3

    def test_clear_history(self) -> None:
        s = ToolSandbox()
        s._executions.append(SandboxResult(value=1))
        s.clear_history()
        assert s.history() == []


class TestSingleton:
    def test_default_singleton(self) -> None:
        s1 = get_default_sandbox()
        s2 = get_default_sandbox()
        assert s1 is s2

    def test_reset(self) -> None:
        s1 = get_default_sandbox()
        reset_default_sandbox()
        s2 = get_default_sandbox()
        assert s1 is not s2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import tool_sandbox

        assert len(tool_sandbox.__all__) == 6


class TestRealisticExample:
    async def test_safe_calculator_tool(self) -> None:
        """Realistic: safe calculator tool wrapped в sandbox."""
        s = ToolSandbox(SandboxConfig(
            max_cpu_seconds=2.0,
            max_memory_mb=64,
            allow_network=False,
            allow_filesystem=False,
            mode=SandboxMode.ENFORCE,
        ))

        def calculate(operation: str, a: float, b: float) -> dict:
            ops = {
                "add": a + b,
                "sub": a - b,
                "mul": a * b,
                "div": a / b if b != 0 else None,
            }
            return {"result": ops.get(operation)}

        wrapped = s.wrap(calculate)
        result = await s.execute(wrapped, "add", 10, 5)
        assert result.success
        assert result.value == {"result": 15}

    async def test_dangerous_tool_rejected(self) -> None:
        """Tool name suggests network access → blocked under strict mode."""
        s = ToolSandbox(SandboxConfig(
            allow_network=False,
            allow_filesystem=False,
            mode=SandboxMode.ENFORCE,
        ))

        def fetch_external_api():
            return "leaked"

        wrapped = s.wrap(fetch_external_api)
        result = await s.execute(wrapped)
        # Network access denied → success=False.
        assert result.success is False
        assert "network_access_denied" in result.policy_violations
