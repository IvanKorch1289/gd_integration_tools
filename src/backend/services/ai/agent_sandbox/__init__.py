"""AgentSandbox subpackage (W9 P2-13 Phase 5).

W9 P2-13 Phase 5 (cycle 153, MINIMAX plan): извлечено из
``services/ai/agent_sandbox.py`` (601 LOC god-module) в package с 5 cohesion
submodules (см. ADR-0330).

Back-compat: ``services/ai/agent_sandbox.py`` (singular, файл) → thin re-export shim.
``services/ai/__init__.py`` (public API facade) без изменений.

Public API:
    from src.backend.services.ai.agent_sandbox import (  # noqa: F401 — re-export
        InProcessAgentSandbox, ProcessPoolAgentSandbox, E2BAgentSandbox,
        AgentSandboxSelector, resolve_agent_sandbox,
        get_process_pool_agent_sandbox,
        AgentSandboxConfigError, AgentSandboxTimeoutError,
    )

Submodules:
    _types.py — AgentSandboxConfigError, AgentSandboxTimeoutError
    _in_process.py — InProcessAgentSandbox + _sync_run_react helper (DEPRECATED)
    _process_pool.py — ProcessPoolAgentSandbox (default-OFF-safe)
    _e2b.py — E2BAgentSandbox (cloud sandbox, opt-in)
    _selector.py — AgentSandboxSelector + resolve_agent_sandbox + singleton
"""

from __future__ import annotations

from src.backend.services.ai.agent_sandbox._e2b import (  # noqa: F401 — re-export
    E2BAgentSandbox as E2BAgentSandbox,
)
from src.backend.services.ai.agent_sandbox._in_process import (  # noqa: F401 — re-export
    InProcessAgentSandbox as InProcessAgentSandbox,
)
from src.backend.services.ai.agent_sandbox._process_pool import (  # noqa: F401 — re-export
    ProcessPoolAgentSandbox as ProcessPoolAgentSandbox,
)
from src.backend.services.ai.agent_sandbox._selector import (  # noqa: F401 — re-export
    AgentSandboxSelector as AgentSandboxSelector,
)
from src.backend.services.ai.agent_sandbox._selector import (  # noqa: F401 — re-export
    get_process_pool_agent_sandbox as get_process_pool_agent_sandbox,
)
from src.backend.services.ai.agent_sandbox._selector import (  # noqa: F401 — re-export
    resolve_agent_sandbox as resolve_agent_sandbox,
)
from src.backend.services.ai.agent_sandbox._types import (  # noqa: F401 — re-export
    AgentSandboxConfigError as AgentSandboxConfigError,
)
from src.backend.services.ai.agent_sandbox._types import (  # noqa: F401 — re-export
    AgentSandboxTimeoutError as AgentSandboxTimeoutError,
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
