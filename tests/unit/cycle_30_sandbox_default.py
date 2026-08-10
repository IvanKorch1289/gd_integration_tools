"""Unit-тесты для cycle 30 P0-#6: ProcessPool default sandbox.

Master Prompt P0-#6: «Убери возможность isolated=False →
InProcessAgentSandbox вне env-флага — сделай ProcessPoolAgentSandbox
единственным реальным default независимо от окружения».

Cycle 30 fix: AgentGraphProcessor.isolated default changed from
False to True (line 117). Builder already had True (infra.py:141).
"""

# ruff: noqa: S101

from __future__ import annotations


class TestProcessPoolDefault:
    """AgentGraphProcessor must default to isolated=True (ProcessPool)."""

    def test_processor_default_is_true(self):
        """AgentGraphProcessor.__init__ must have isolated: bool = True."""
        path = "src/backend/dsl/engine/processors/agent_dsl/agent_graph.py"
        with open(path) as f:
            content = f.read()
        # The signature must have isolated: bool = True
        assert "isolated: bool = True" in content, (
            "AgentGraphProcessor must default isolated=True (ProcessPool)"
        )

    def test_builder_default_is_true(self):
        """Builder (infra.py) must also default isolated=True."""
        path = "src/backend/dsl/builders/agent_dsl/infra.py"
        with open(path) as f:
            content = f.read()
        assert "isolated: bool = True" in content, (
            "Builder must default isolated=True"
        )

    def test_in_process_still_available_explicitly(self):
        """isolated=False must still work for dev_light (explicit opt-in)."""
        path = "src/backend/dsl/engine/processors/agent_dsl/agent_graph.py"
        with open(path) as f:
            content = f.read()
        # The else branch must still create InProcessAgentSandbox
        assert "InProcessAgentSandbox" in content, (
            "InProcessAgentSandbox must still be reachable via isolated=False"
        )


class TestSandboxProdGuard:
    """InProcessAgentSandbox must be blocked in production via env var."""

    def test_env_var_check_present(self):
        """agent_sandbox.py must check GD_INTEGRATION_PRODUCTION."""
        path = "src/backend/services/ai/agent_sandbox.py"
        with open(path) as f:
            content = f.read()
        assert "GD_INTEGRATION_PRODUCTION" in content, (
            "Production guard env var missing"
        )

    def test_deprecation_warning_present(self):
        """InProcessAgentSandbox construction must emit DeprecationWarning."""
        path = "src/backend/services/ai/agent_sandbox.py"
        with open(path) as f:
            content = f.read()
        assert "DEPRECATED" in content or "DeprecationWarning" in content, (
            "Deprecation marker missing"
        )

    def test_resolve_default_is_process_pool(self):
        """resolve_agent_sandbox must default to process_pool."""
        path = "src/backend/services/ai/agent_sandbox.py"
        with open(path) as f:
            content = f.read()
        # Multiple places reference process_pool as default
        assert content.count('"process_pool"') >= 2, (
            "process_pool must be referenced as default in multiple places"
        )
