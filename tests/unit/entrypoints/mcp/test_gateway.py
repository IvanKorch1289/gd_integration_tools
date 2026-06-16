"""Unit tests for MCPGateway."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.backend.entrypoints.mcp import gateway
from src.backend.entrypoints.mcp.gateway import (
    MCPGateway,
    _check_feature_flag,
    _resolve_auth_provider,
    create_mcp_gateway,
)


class TestCheckFeatureFlag:
    """Tests for _check_feature_flag."""

    def test_enabled(self) -> None:
        with patch(
            "src.backend.entrypoints.mcp.gateway.feature_flags",
            MagicMock(mcp_gateway_namespaces_enabled=True),
        ):
            assert _check_feature_flag() is True

    def test_disabled(self) -> None:
        with patch(
            "src.backend.entrypoints.mcp.gateway.feature_flags",
            MagicMock(mcp_gateway_namespaces_enabled=False),
        ):
            assert _check_feature_flag() is False

    def test_fallback_on_exception(self) -> None:
        class BadFlags:
            @property
            def mcp_gateway_namespaces_enabled(self) -> bool:
                raise ImportError("nope")

        with patch(
            "src.backend.entrypoints.mcp.gateway.feature_flags", BadFlags()
        ):
            assert _check_feature_flag() is False


class TestResolveAuthProvider:
    """Tests for _resolve_auth_provider."""

    def test_returns_none_when_auth_disabled(self) -> None:
        with patch(
            "src.backend.entrypoints.mcp.gateway.ai_2026",
            MagicMock(mcp_settings=MagicMock(tool_authz_enabled=False)),
        ):
            assert _resolve_auth_provider() is None

    def test_returns_none_when_issuer_missing(self) -> None:
        with patch(
            "src.backend.entrypoints.mcp.gateway.ai_2026",
            MagicMock(
                mcp_settings=MagicMock(tool_authz_enabled=True, sso_issuer_url=None)
            ),
        ):
            assert _resolve_auth_provider() is None

    def test_returns_verifier_when_configured(self) -> None:
        mock_verifier = MagicMock()
        with patch(
            "src.backend.entrypoints.mcp.gateway.ai_2026",
            MagicMock(
                mcp_settings=MagicMock(
                    tool_authz_enabled=True, sso_issuer_url="https://sso.local"
                )
            ),
        ):
            with patch(
                "src.backend.entrypoints.mcp.gateway.JWTVerifier",
                return_value=mock_verifier,
            ):
                result = _resolve_auth_provider()
        assert result is mock_verifier

    def test_returns_none_on_jwt_verifier_import_error(self) -> None:
        with patch(
            "src.backend.entrypoints.mcp.gateway.ai_2026",
            MagicMock(
                mcp_settings=MagicMock(
                    tool_authz_enabled=True, sso_issuer_url="https://sso.local"
                )
            ),
        ):
            with patch(
                "src.backend.entrypoints.mcp.gateway.JWTVerifier",
                side_effect=ImportError("nope"),
            ):
                assert _resolve_auth_provider() is None


class TestMCPGateway:
    """Tests for :class:`MCPGateway`."""

    def test_init(self) -> None:
        gw = MCPGateway(auth="auth_obj")
        assert gw._auth == "auth_obj"

    def test_create_server_without_auth(self) -> None:
        gw = MCPGateway(auth=None)
        mock_mcp = MagicMock()
        with patch.object(gateway, "FastMCP", return_value=mock_mcp):
            with patch.object(gw, "_register_namespaces"):
                with patch.object(gw, "_register_workflow_tools"):
                    with patch.object(gw, "_register_system_tools"):
                        result = gw.create_server()
        assert result is mock_mcp
        mock_mcp.tool.assert_not_called()

    def test_create_server_with_auth(self) -> None:
        auth = MagicMock()
        gw = MCPGateway(auth=auth)
        mock_mcp = MagicMock()
        with patch.object(gateway, "FastMCP", return_value=mock_mcp):
            with patch.object(gw, "_register_namespaces"):
                with patch.object(gw, "_register_workflow_tools"):
                    with patch.object(gw, "_register_system_tools"):
                        result = gw.create_server()
        assert result is mock_mcp

    def test_auto_register_skills_no_registry(self) -> None:
        gw = MCPGateway()
        with patch(
            "src.backend.entrypoints.mcp.gateway.SkillRegistry",
            side_effect=ImportError("nope"),
        ):
            assert gw.auto_register_skills() == 0

    def test_auto_register_skills_success(self) -> None:
        gw = MCPGateway()
        mock_registry = MagicMock()
        mock_registry.list_skills.return_value = ["skill1", "skill2"]
        mock_namespace = MagicMock()
        mock_namespace.name = "credit"

        with patch(
            "src.backend.entrypoints.mcp.gateway.SkillRegistry",
            return_value=mock_registry,
        ):
            with patch(
                "src.backend.entrypoints.mcp.gateway.get_namespace_for_action",
                return_value=mock_namespace,
            ):
                assert gw.auto_register_skills() == 2


class TestCreateMcpGateway:
    """Tests for create_mcp_gateway."""

    def test_returns_server(self) -> None:
        with patch(
            "src.backend.entrypoints.mcp.gateway._resolve_auth_provider",
            return_value=None,
        ):
            with patch.object(MCPGateway, "create_server", return_value="server"):
                assert create_mcp_gateway() == "server"
