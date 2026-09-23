"""Tool Sandbox — bounded execution helper (Wave 3 #21).

Проблема:
    Tool call от AI-агента может:
    - Запустить RCE-код через eval/exec.
    - Читать host filesystem.
    - Делать внешние network calls.
    - Потреблять CPU/memory без лимитов.

Решение:
    ``ToolSandbox`` — bounded executor:

    1. ``SandboxConfig`` — limits (max_memory_mb, max_cpu_seconds, timeout).
    2. ``SandboxedTool`` — wrapper для function с execution limits.
    3. ``SandboxResult`` — result + metrics (execution time, memory).
    4. ``ToolPolicyViolation`` — exception при превышении.
    5. Pure-Python (uses asyncio + resource monitoring).
    6. Production → process pool / container isolation (E2B).

Использование::

    from src.backend.core.tool_sandbox import (  # noqa: F401 — re-export
        ToolSandbox, SandboxConfig, SandboxedTool, ToolPolicyViolation,
    )

    sandbox = ToolSandbox(SandboxConfig(
        max_cpu_seconds=10.0,
        max_memory_mb=256,
        allow_filesystem=False,
        allow_network=False,
    ))

    @sandbox.wrap
    async def risky_tool(input: str) -> dict:
        # Код, который не должен иметь доступа к FS/network.
        return {"result": len(input)}

    result = await risky_tool("hello")
    assert result.value == {"result": 5}
"""

from __future__ import annotations

from src.backend.core.tool_sandbox.sandbox import (  # noqa: F401 — re-export
    SandboxConfig,
    SandboxedTool,
    SandboxMode,
    SandboxResult,
    ToolPolicyViolation,
    ToolSandbox,
)

__all__ = (
    "SandboxConfig",
    "SandboxMode",
    "SandboxResult",
    "SandboxedTool",
    "ToolPolicyViolation",
    "ToolSandbox",
)
