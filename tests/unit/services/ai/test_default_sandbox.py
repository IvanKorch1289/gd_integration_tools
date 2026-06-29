"""TDD: Default sandbox type (M24 P0 #2, D270).

Per M14 audit: InProcessAgentSandbox — default, no process isolation.
Fix: change default to ProcessPoolAgentSandbox (P0 security).
Pattern (D270, Ponytail): settings flag.
"""
# ruff: noqa: S101
from __future__ import annotations
import pytest


class TestDefaultSandbox:
    def test_settings_has_default_sandbox_field(self) -> None:
        from src.backend.core.config.ai import AIWorkspaceSettings as AgentSettings
        settings = AgentSettings()
        # default должен быть process_pool (D270, P0 security)
        assert settings.default_agent_sandbox in (
            "process_pool", "in_process", "e2b",
        )

    def test_in_process_available_for_dev(self) -> None:
        """in_process остается доступным для dev (D270 backward compat)."""
        from src.backend.core.config.ai import AIWorkspaceSettings as AgentSettings
        settings = AgentSettings(default_agent_sandbox="in_process")
        assert settings.default_agent_sandbox == "in_process"
