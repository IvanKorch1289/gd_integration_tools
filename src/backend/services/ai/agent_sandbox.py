"""Backward-compat shim — ``agent_sandbox`` стал package.

W9 P2-13 Phase 5 (cycle 153, MINIMAX plan): ``agent_sandbox.py`` (601 LOC
god-module) → ``agent_sandbox/`` package с 5 cohesion submodules (см. ADR-0330).
Этот модуль — thin re-export shim для backward-compat:
``from services.ai.agent_sandbox import X`` продолжает работать для всех
8 публичных имён.

Migration::

    # До (W9 P2-13 Phase 5 — still works через этот shim):
    from src.backend.services.ai.agent_sandbox import (
        InProcessAgentSandbox, ProcessPoolAgentSandbox, E2BAgentSandbox,
        AgentSandboxSelector, resolve_agent_sandbox,
        get_process_pool_agent_sandbox,
        AgentSandboxConfigError, AgentSandboxTimeoutError,
    )

    # После (canonical, рекомендуется для нового кода):
    from src.backend.services.ai.agent_sandbox import (
        InProcessAgentSandbox, ProcessPoolAgentSandbox, E2BAgentSandbox,
        AgentSandboxSelector, resolve_agent_sandbox,
        get_process_pool_agent_sandbox,
        AgentSandboxConfigError, AgentSandboxTimeoutError,
    )
    # Тот же путь — split прозрачен для consumers.

Removal: запланирован на cycle 162 (отдельный cleanup wave после telemetry
audit consumer migration).
"""

from __future__ import annotations

from src.backend.services.ai.agent_sandbox import (  # type: ignore[attr-defined]
    AgentSandboxConfigError as AgentSandboxConfigError,
)
from src.backend.services.ai.agent_sandbox import (
    AgentSandboxSelector as AgentSandboxSelector,
)
from src.backend.services.ai.agent_sandbox import (
    AgentSandboxTimeoutError as AgentSandboxTimeoutError,
)
from src.backend.services.ai.agent_sandbox import E2BAgentSandbox as E2BAgentSandbox
from src.backend.services.ai.agent_sandbox import (
    InProcessAgentSandbox as InProcessAgentSandbox,
)
from src.backend.services.ai.agent_sandbox import (
    ProcessPoolAgentSandbox as ProcessPoolAgentSandbox,
)
from src.backend.services.ai.agent_sandbox import (
    get_process_pool_agent_sandbox as get_process_pool_agent_sandbox,
)
from src.backend.services.ai.agent_sandbox import (
    resolve_agent_sandbox as resolve_agent_sandbox,
)

__all__ = (
    "AgentSandboxConfigError",
    "AgentSandboxSelector",
    "AgentSandboxTimeoutError",
    "E2BAgentSandbox",
    "InProcessAgentSandbox",
    "ProcessPoolAgentSandbox",
    "get_process_pool_agent_sandbox",
    "resolve_agent_sandbox",
)
