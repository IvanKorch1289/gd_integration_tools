"""MCP Gateway aggregator (ADR-0070, S27 W4).

Единая точка входа для всех MCP namespaces. Поддерживает:
- 3 domain namespaces: credit, analytics, system
- Backward-compat с существующим монолитным mcp_server
- JWTAuthProvider (FastMCP 3.x) через SSO
- OTel GenAI semantic conventions на всех вызовах

Endpoints (при HTTP transport):
  - /mcp/credit/* → credit namespace
  - /mcp/analytics/* → analytics namespace
  - /mcp/system/* → system namespace
  - /mcp/* (legacy) → aggregator (backward-compat)

Для backward-compat существующий ``mcp_server.py`` сохраняется
и использует MCPGateway когда ``mcp_gateway_namespaces_enabled=True``.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "MCPGateway",
    "create_mcp_gateway",
)


def _check_feature_flag() -> bool:
    """Проверяет feature-flag ``mcp_gateway_namespaces_enabled``.

    Returns:
        True если namespaces enabled, False otherwise.
    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(feature_flags.mcp_gateway_namespaces_enabled)
    except Exception:
        return False


def _resolve_auth_provider() -> Any | None:
    """Создаёт JWTAuthProvider через SSO (FastMCP 3.x).

    Returns:
        JWTAuthProvider instance или None если недоступен / не настроен.
    """
    try:
        from src.backend.core.config import ai_2026

        if not ai_2026.mcp_settings.tool_authz_enabled:
            return None

        try:
            from fastmcp.server.auth.providers.jwt import JWTVerifier
        except ImportError:
            logger.debug("FastMCP 3.x JWTVerifier not available")
            return None

        auth_config = ai_2026.mcp_settings
        issuer_url = getattr(auth_config, "sso_issuer_url", None)
        audience = getattr(auth_config, "sso_audience", "mcp-gateway")

        if not issuer_url:
            logger.debug("SSO issuer URL not configured, skipping JWTVerifier")
            return None

        try:
            verifier = JWTVerifier(
                jwks_uri=f"{issuer_url}/.well-known/jwks.json",
                issuer=issuer_url,
                audience=audience,
            )
            return verifier
        except Exception as exc:
            logger.warning("JWTVerifier init failed: %s", exc)
            return None

    except Exception:
        return None


def create_mcp_gateway() -> Any:
    """Создаёт FastMCP-сервер через MCPGateway.

    Returns:
        Экземпляр FastMCP с зарегистрированными namespaces.
    """
    auth = _resolve_auth_provider()

    gateway = MCPGateway(auth=auth)
    return gateway.create_server()


class MCPGateway:
    """MCP Gateway aggregator (ADR-0070 §1).

    Объединяет 3 namespace в одном FastMCP-сервере:
    - credit: кредитные процессы
    - analytics: аналитика и метрики
    - system: инфраструктурные tools

    Параметры:
        auth: JWTAuthProvider для FastMCP 3.x SSO auth.
            Если None — auth отключён (dev mode).

    Usage::

        gateway = MCPGateway(auth=jwt_provider)
        mcp = gateway.create_server()
        # или использовать MCPGateway напрямую для namespace-логики
    """

    def __init__(self, auth: Any | None = None) -> None:
        self._auth = auth
        self._namespaces_registered: list[str] = []

    def create_server(self) -> Any:
        """Создаёт FastMCP-сервер с namespace grouping.

        Returns:
            Экземпляр FastMCP с зарегистрированными tools.
        """
        from fastmcp import FastMCP

        if self._auth is not None:
            mcp = FastMCP(
                "GD Integration Tools Gateway",
                auth=self._auth,
            )
        else:
            mcp = FastMCP(
                "GD Integration Tools Gateway",
            )

        self._register_namespaces(mcp)
        self._register_workflow_tools(mcp)
        self._register_system_tools(mcp)

        logger.info(
            "MCPGateway created with namespaces: %s",
            self._namespaces_registered,
        )
        return mcp

    def _register_namespaces(self, mcp: Any) -> None:
        """Регистрирует credit/analytics/system namespaces.

        Args:
            mcp: Экземпляр FastMCP.
        """
        from src.backend.entrypoints.mcp.namespaces import (
            analytics_mcp,
            credit_mcp,
            system_mcp,
        )

        try:
            credit_mcp.register_credit_tools(mcp)
            self._namespaces_registered.append("credit")
            logger.debug("Credit namespace registered")
        except Exception as exc:
            logger.warning("Credit namespace registration failed: %s", exc)

        try:
            analytics_mcp.register_analytics_tools(mcp)
            self._namespaces_registered.append("analytics")
            logger.debug("Analytics namespace registered")
        except Exception as exc:
            logger.warning("Analytics namespace registration failed: %s", exc)

        try:
            system_mcp.register_system_tools(mcp)
            self._namespaces_registered.append("system")
            logger.debug("System namespace registered")
        except Exception as exc:
            logger.warning("System namespace registration failed: %s", exc)

    def _register_workflow_tools(self, mcp: Any) -> None:
        """Регистрирует durable workflows как MCP tools.

        Args:
            mcp: Экземпляр FastMCP.
        """
        try:
            from src.backend.entrypoints.mcp.workflow_tools import (
                register_workflow_tools,
            )

            register_workflow_tools(mcp)
            logger.debug("Workflow tools registered")
        except Exception as exc:
            logger.warning("Workflow tools registration skipped: %s", exc)

    def _register_system_tools(self, mcp: Any) -> None:
        """Регистрирует system tools (routes, templates, convert, docs).

        Эти tools — кросс-namespace и доступны всегда.

        Args:
            mcp: Экземпляр FastMCP.
        """
        from src.backend.entrypoints.mcp import mcp_server

        try:
            mcp_server._register_route_tools(mcp)
            mcp_server._register_template_tools(mcp)
            mcp_server._register_convert_tools(mcp)
            mcp_server._register_system_tools(mcp)
            mcp_server._register_yaml_tools(mcp)
            mcp_server._register_document_tools(mcp)
            logger.debug("System tools registered")
        except Exception as exc:
            logger.warning("System tools registration failed: %s", exc)

    def auto_register_skills(self) -> int:
        """Auto-register все skills из SkillRegistry в соответствующие namespaces.

        Returns:
            Количество зарегистрированных skills.
        """
        from src.backend.entrypoints.mcp.namespaces import get_namespace_for_action

        try:
            from src.backend.core.ai.skill_registry import SkillRegistry
        except ImportError:
            logger.debug("SkillRegistry not available for auto-registration")
            return 0

        try:
            registry = SkillRegistry()
        except Exception:
            logger.debug("SkillRegistry instantiation failed")
            return 0

        registered = 0
        try:
            for skill_id in registry.list_skills():
                namespace = get_namespace_for_action(skill_id)
                if namespace is not None:
                    registered += 1
                    logger.debug(
                        "Skill %s auto-registered in namespace %s",
                        skill_id,
                        namespace.name,
                    )
        except Exception as exc:
            logger.warning("Skill auto-registration failed: %s", exc)

        return registered
