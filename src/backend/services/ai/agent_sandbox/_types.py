"""Exceptions для AgentSandbox (W9 P2-13 Phase 5).

W9 P2-13 Phase 5 (cycle 153): извлечено из ``services/ai/agent_sandbox.py``
(601 LOC god-module). Содержит кастомные exceptions для sandbox errors.

Back-compat: ``services/ai/agent_sandbox.py`` (file) продолжает re-export
через thin ``__init__.py`` shim (см. ADR-0330).
"""

from __future__ import annotations


class AgentSandboxConfigError(Exception):
    """Sandbox missing required config (e.g. E2B API key).

    Distinct from generic exceptions — caller может map → HTTP 503.
    """


class AgentSandboxTimeoutError(Exception):
    """Sandbox execution превысил timeout (max_wall_time_s)."""
