"""Cycle 13: default agent timeouts (centralized constants).

Per D421, hardcoded timeouts in agent_dsl processors previously
duplicated the same magic numbers across files. Single source of
truth for agent execution timeouts. Each processor still allows
explicit override via constructor arg (preserves public API).
"""
from __future__ import annotations

DEFAULT_AGENT_TIMEOUT_S: float = 300.0
"""Default agent execution timeout (5 minutes) — covers typical
LLM tool-call chains without making long-running workflows fail."""

DEFAULT_MCP_TIMEOUT_S: float = 30.0
"""Default MCP tool call timeout — MCP server should be fast;
long calls indicate a different problem (use --no-progress flag)."""

__all__ = (
    "DEFAULT_AGENT_TIMEOUT_S",
    "DEFAULT_MCP_TIMEOUT_S",
)
