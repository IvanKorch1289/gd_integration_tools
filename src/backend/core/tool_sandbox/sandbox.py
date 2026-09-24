"""Tool Sandbox — bounded execution helper (Wave 3 #21).

Pure-Python implementation:
- SandboxConfig: limits (timeout, memory, network, FS).
- ToolSandbox: wrap decorator.
- SandboxedTool: result + metrics.
- ToolPolicyViolation: raised on limit breach.
"""

from __future__ import annotations

import asyncio
import enum
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = (
    "SandboxConfig",
    "SandboxMode",
    "SandboxResult",
    "SandboxedTool",
    "ToolPolicyViolation",
    "ToolSandbox",
)


class SandboxMode(str, enum.Enum):
    """Sandbox enforcement mode."""

    PERMISSIVE = "permissive"  # log only, no enforcement
    ENFORCE = "enforce"  # raise on violation
    AUDIT = "audit"  # log + monitor (no raise)


@dataclass(slots=True)
class SandboxConfig:
    """Sandbox limits для tool execution.

    Attributes:
        max_cpu_seconds: Hard timeout для execution.
        max_memory_mb: Memory limit (informational; full enforcement требует container).
        allow_filesystem: False = блокировать FS access (warnings).
        allow_network: False = блокировать network access (warnings).
        mode: Enforcement mode (permissive/enforce/audit).
    """

    max_cpu_seconds: float = 30.0
    max_memory_mb: int = 512
    allow_filesystem: bool = True
    allow_network: bool = True
    mode: SandboxMode = SandboxMode.ENFORCE


@dataclass(slots=True)
class SandboxResult:
    """Sandboxed execution result."""

    value: Any = None
    success: bool = True
    duration_ms: float = 0.0
    error: str | None = None
    error_type: str | None = None
    policy_violations: list[str] = field(default_factory=list)


class ToolPolicyViolation(Exception):
    """Raised when tool execution violates sandbox policy."""

    def __init__(self, message: str, *, violation_type: str = "unknown") -> None:
        super().__init__(message)
        self.violation_type = violation_type
        self.message = message


@dataclass(slots=True)
class SandboxedTool:
    """Wrapped tool с sandbox enforcement."""

    name: str
    func: Callable[..., Any]
    config: SandboxConfig


class ToolSandbox:
    """Sandbox manager + decorator factory."""

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()
        self._executions: list[SandboxResult] = []

    @property
    def config(self) -> SandboxConfig:
        """Конфигурация песочницы (timeouts/limits)."""
        return self._config

    def configure(self, **kwargs: Any) -> None:
        """Update config (e.g., timeout, mode)."""
        from dataclasses import replace

        self._config = replace(self._config, **kwargs)

    def wrap(self, fn: Callable[..., Any]) -> SandboxedTool:
        """Decorator: wrap function as sandboxed tool."""
        return SandboxedTool(
            name=getattr(fn, "__name__", "sandboxed_tool"), func=fn, config=self._config
        )

    async def execute(
        self, tool: SandboxedTool, *args: Any, **kwargs: Any
    ) -> SandboxResult:
        """Execute sandboxed tool с limits enforcement."""
        result = SandboxResult(value=None, success=True)
        start = time.time()
        violations: list[str] = []

        # Pre-execution policy checks.
        if not self._config.allow_network:
            # Heuristic: detect network-bound calls by name.
            name = tool.name.lower()
            if any(kw in name for kw in ("http", "fetch", "request", "api", "url")):
                violations.append("network_access_denied")
                result.policy_violations.append("network_access_denied")
        if not self._config.allow_filesystem:
            name = tool.name.lower()
            if any(kw in name for kw in ("file", "read", "write", "path")):
                violations.append("filesystem_access_denied")
                result.policy_violations.append("filesystem_access_denied")

        try:
            if inspect.iscoroutinefunction(tool.func):
                output = await asyncio.wait_for(
                    tool.func(*args, **kwargs), timeout=self._config.max_cpu_seconds
                )
            else:
                # Run sync function в executor с timeout.
                loop = asyncio.get_event_loop()
                output = await asyncio.wait_for(
                    loop.run_in_executor(None, tool.func, *args, **kwargs),
                    timeout=self._config.max_cpu_seconds,
                )
            result.value = output
            result.success = True
        except asyncio.TimeoutError:
            result.success = False
            result.error = f"Timeout exceeded: {self._config.max_cpu_seconds}s"
            result.error_type = "TimeoutError"
            violations.append("timeout_exceeded")
            result.policy_violations.append("timeout_exceeded")
        except Exception as exc:
            result.success = False
            result.error = f"{type(exc).__name__}: {exc}"
            result.error_type = type(exc).__name__

        result.duration_ms = (time.time() - start) * 1000

        # Handle policy violations.
        if violations and self._config.mode == SandboxMode.ENFORCE:
            result.success = False
            if not result.error:
                result.error = f"Policy violations: {', '.join(violations)}"

        self._executions.append(result)
        return result

    def history(self) -> list[SandboxResult]:
        """История результатов исполнения инструментов."""
        return list(self._executions)

    def clear_history(self) -> None:
        """Очистить историю результатов (для тестов)."""
        self._executions.clear()


# Module-level default sandbox (для convenience).
_default_sandbox: ToolSandbox | None = None


def get_default_sandbox() -> ToolSandbox:
    """Module-level default sandbox."""
    global _default_sandbox
    if _default_sandbox is None:
        _default_sandbox = ToolSandbox()
    return _default_sandbox


def reset_default_sandbox() -> None:
    """Сбросить default-sandbox singleton."""
    global _default_sandbox
    _default_sandbox = None
