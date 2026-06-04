"""Tests for MCP namespace aggregation (ADR-0070 §1, S27 W4).

Verifies:
- MCPNamespace.get_namespace_for_action
- Namespace tool registration
- Backward-compat with legacy mcp_server
"""

from __future__ import annotations

import pytest


class TestMCPNamespace:
    """Tests for MCPNamespace dataclass and helpers."""

    def test_namespace_dataclass_fields(self) -> None:
        """MCPNamespace has required fields."""
        from src.backend.entrypoints.mcp.namespaces import (
            MCPNamespace,
            CREDIT_NAMESPACE,
            ANALYTICS_NAMESPACE,
            SYSTEM_NAMESPACE,
        )

        assert CREDIT_NAMESPACE.name == "credit"
        assert CREDIT_NAMESPACE.description
        assert CREDIT_NAMESPACE.action_prefixes == ("credit.",)
        assert CREDIT_NAMESPACE.capabilities_required == ("mcp.gateway.invoke.credit",)

        assert ANALYTICS_NAMESPACE.name == "analytics"
        assert ANALYTICS_NAMESPACE.action_prefixes == ("analytics.", "metrics.")
        assert ANALYTICS_NAMESPACE.capabilities_required == (
            "mcp.gateway.invoke.analytics",
        )

        assert SYSTEM_NAMESPACE.name == "system"
        assert "system." in SYSTEM_NAMESPACE.action_prefixes
        assert "tech." in SYSTEM_NAMESPACE.action_prefixes
        assert "health." in SYSTEM_NAMESPACE.action_prefixes
        assert "admin." in SYSTEM_NAMESPACE.action_prefixes
        assert SYSTEM_NAMESPACE.capabilities_required == ("mcp.gateway.invoke.system",)

    def test_get_namespace_for_credit_action(self) -> None:
        """credit.* actions map to CREDIT_NAMESPACE."""
        from src.backend.entrypoints.mcp.namespaces import (
            get_namespace_for_action,
            CREDIT_NAMESPACE,
        )

        ns = get_namespace_for_action("credit.score.calculate")
        assert ns is CREDIT_NAMESPACE

        ns = get_namespace_for_action("credit.underwriting.decision")
        assert ns is CREDIT_NAMESPACE

        ns = get_namespace_for_action("credit.application.submit")
        assert ns is CREDIT_NAMESPACE

    def test_get_namespace_for_analytics_action(self) -> None:
        """analytics.* and metrics.* actions map to ANALYTICS_NAMESPACE."""
        from src.backend.entrypoints.mcp.namespaces import (
            get_namespace_for_action,
            ANALYTICS_NAMESPACE,
        )

        ns = get_namespace_for_action("analytics.report.generate")
        assert ns is ANALYTICS_NAMESPACE

        ns = get_namespace_for_action("metrics.dashboard.fetch")
        assert ns is ANALYTICS_NAMESPACE

    def test_get_namespace_for_system_action(self) -> None:
        """system.*, tech.*, health.*, admin.* actions map to SYSTEM_NAMESPACE."""
        from src.backend.entrypoints.mcp.namespaces import (
            get_namespace_for_action,
            SYSTEM_NAMESPACE,
        )

        for prefix in ("system.", "tech.", "health.", "admin."):
            ns = get_namespace_for_action(f"{prefix}status")
            assert ns is SYSTEM_NAMESPACE, f"{prefix} should map to SYSTEM_NAMESPACE"

    def test_get_namespace_for_unknown_action(self) -> None:
        """Actions not in any namespace return None."""
        from src.backend.entrypoints.mcp.namespaces import get_namespace_for_action

        ns = get_namespace_for_action("unknown.action")
        assert ns is None

        ns = get_namespace_for_action("custom.skill.calculate")
        assert ns is None

    def test_list_namespaces_returns_all_three(self) -> None:
        """list_namespaces returns credit, analytics, system."""
        from src.backend.entrypoints.mcp.namespaces import (
            list_namespaces,
            CREDIT_NAMESPACE,
            ANALYTICS_NAMESPACE,
            SYSTEM_NAMESPACE,
            AI_NAMESPACE,
        )

        namespaces = list_namespaces()
        assert len(namespaces) == 4
        assert CREDIT_NAMESPACE in namespaces
        assert ANALYTICS_NAMESPACE in namespaces
        assert SYSTEM_NAMESPACE in namespaces
        assert AI_NAMESPACE in namespaces


class TestMCPClientSpec:
    """Tests for MCPClientSpec model."""

    def test_mcp_client_spec_defaults(self) -> None:
        """MCPClientSpec has sensible defaults."""
        from src.backend.infrastructure.clients.external.mcp_registry import (
            MCPClientSpec,
        )

        spec = MCPClientSpec(name="test", url="https://example.com/mcp")
        assert spec.auth_provider == "none"
        assert spec.capability_required == ""
        assert spec.waf_policy == "strict"
        assert spec.timeout_s == 10.0
        assert spec.headers == {}

    def test_mcp_client_spec_full(self) -> None:
        """MCPClientSpec accepts all fields."""
        from src.backend.infrastructure.clients.external.mcp_registry import (
            MCPClientSpec,
        )

        spec = MCPClientSpec(
            name="anthropic-search",
            url="https://mcp.anthropic.com/v1/search",
            auth_provider="jwt",
            capability_required="net.outbound.mcp.anthropic.com:external",
            waf_policy="strict",
            timeout_s=15.0,
            headers={"X-Custom": "value"},
        )
        assert spec.name == "anthropic-search"
        assert spec.auth_provider == "jwt"
        assert spec.timeout_s == 15.0


class TestMCPClientRegistry:
    """Tests for MCPClientRegistry."""

    def test_registry_register_and_list(self) -> None:
        """register() and list_registered() work."""
        from src.backend.infrastructure.clients.external.mcp_registry import (
            MCPClientRegistry,
            MCPClientSpec,
        )

        registry = MCPClientRegistry()
        spec = MCPClientSpec(name="test", url="https://test.com")
        registry.register(spec)

        clients = registry.list_registered()
        assert len(clients) == 1
        assert clients[0].name == "test"

    def test_registry_get(self) -> None:
        """get() returns registered client."""
        from src.backend.infrastructure.clients.external.mcp_registry import (
            MCPClientRegistry,
            MCPClientSpec,
        )

        registry = MCPClientRegistry()
        spec = MCPClientSpec(name="test", url="https://test.com")
        registry.register(spec)

        found = registry.get("test")
        assert found is spec

        not_found = registry.get("missing")
        assert not_found is None

    def test_registry_load_from_yaml_empty(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """load_from_yaml with empty clients list."""
        from src.backend.infrastructure.clients.external.mcp_registry import (
            MCPClientRegistry,
        )

        config = tmp_path / "mcp_clients.yaml"
        config.write_text("clients: []\n")

        registry = MCPClientRegistry()
        count = registry.load_from_yaml(str(config))
        assert count == 0

    def test_registry_load_from_yaml_not_found(self) -> None:
        """load_from_yaml returns 0 for missing file."""
        from src.backend.infrastructure.clients.external.mcp_registry import (
            MCPClientRegistry,
        )

        registry = MCPClientRegistry()
        count = registry.load_from_yaml("/nonexistent/mcp_clients.yaml")
        assert count == 0


class TestCapabilityRegistration:
    """Tests for per-namespace capability registration."""

    def test_namespace_capabilities_in_vocabulary(self) -> None:
        """mcp.gateway.invoke.{credit,analytics,system} are registered."""
        from src.backend.core.security.capabilities.vocabulary import (
            build_default_vocabulary,
        )

        vocab = build_default_vocabulary()

        for ns in ("credit", "analytics", "system"):
            cap_name = f"mcp.gateway.invoke.{ns}"
            cap = vocab.get(cap_name)
            assert cap is not None, f"{cap_name} should be registered"
            assert ns in cap.description
