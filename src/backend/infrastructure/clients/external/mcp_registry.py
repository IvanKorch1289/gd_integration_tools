"""MCPClientRegistry — trusted external MCP servers (ADR-0070 §2, S27 W4).

Реестр external MCP-серверов (3rd-party SaaS, партнёрские endpoints).
Все запросы проходят через OutboundHttpClient + WAF capability gate.

Config через ``mcp_clients.yaml``::

    clients:
      - name: anthropic-mcp-search
        url: https://mcp.anthropic.com/v1/search
        auth_provider: jwt
        capability_required: net.outbound.mcp.anthropic.com:external
        waf_policy: strict
        timeout_s: 10.0
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.backend.infrastructure.logging.factory import get_logger

if __name__ == "__main__":
    raise SystemExit("Import-only module")

__all__ = ("MCPClientRegistry", "MCPClientSpec", "mcp_client_registry")

logger = get_logger(__name__)


class MCPClientSpec(BaseModel):
    """Спецификация trusted external MCP-сервера (ADR-0070 §2).

    Attributes:
        name: Уникальный identifier (напр. "anthropic-mcp-search").
        url: HTTP endpoint MCP-сервера.
        auth_provider: Тип auth: "jwt", "api_key", "oauth", "none".
        capability_required: Capability required для outbound access
            (напр. "net.outbound.mcp.anthropic.com:external").
        waf_policy: WAF policy: "strict" (default) или "permissive".
        timeout_s: Таймаут запроса в секундах.
        headers: Дополнительные HTTP headers (напр. Authorization).
    """

    name: str = Field(..., description="Уникальный identifier клиента")
    url: str = Field(..., description="HTTP endpoint MCP-сервера")
    auth_provider: str = Field(
        default="none", description="Тип auth: jwt | api_key | oauth | none"
    )
    capability_required: str = Field(
        default="", description="Capability для outbound access к этому endpoint"
    )
    waf_policy: str = Field(
        default="strict", description="WAF policy: strict | permissive"
    )
    timeout_s: float = Field(
        default=10.0, ge=0.1, le=120.0, description="Таймаут запроса (секунды)"
    )
    headers: dict[str, str] = Field(
        default_factory=dict, description="Дополнительные HTTP headers"
    )


class MCPClientRegistry:
    """Реестр trusted external MCP-серверов (ADR-0070 §2).

    Все запросы к external MCP-серверам проходят через:
    1. Capability gate (``net.outbound.<host>:external``)
    2. OutboundHttpClient с WAF policy
    3. Auth provider (JWT / API key / OAuth)

    Usage::

        registry = MCPClientRegistry()
        registry.load_from_yaml("config_profiles/mcp_clients.yaml")

        result = await registry.call(
            "anthropic-mcp-search",
            "search",
            query="What is MCP?",
        )
    """

    def __init__(self) -> None:
        self._clients: dict[str, MCPClientSpec] = {}
        self._http_client: Any | None = None

    def register(self, spec: MCPClientSpec) -> None:
        """Регистрирует external MCP-сервер.

        Args:
            spec: Спецификация клиента.
        """
        self._clients[spec.name] = spec
        logger.info("MCP external client registered: %s (%s)", spec.name, spec.url)

    def load_from_yaml(self, path: str) -> int:
        """Загружает конфигурацию из YAML файла.

        Args:
            path: Путь к ``mcp_clients.yaml``.

        Returns:
            Количество загруженных клиентов.
        """
        import yaml

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning("mcp_clients.yaml not found at %s", path)
            return 0
        except yaml.YAMLError as exc:
            logger.error("Failed to parse mcp_clients.yaml: %s", exc)
            return 0

        clients_data = data.get("clients", []) if isinstance(data, dict) else []
        for client_spec in clients_data:
            try:
                spec = MCPClientSpec(**client_spec)
                self.register(spec)
            except Exception as exc:
                logger.warning("Invalid MCP client spec %s: %s", client_spec, exc)

        return len(self._clients)

    def list_registered(self) -> list[MCPClientSpec]:
        """Возвращает список всех зарегистрированных клиентов.

        Returns:
            Список MCPClientSpec.
        """
        return list(self._clients.values())

    def get(self, name: str) -> MCPClientSpec | None:
        """Возвращает спецификацию клиента по имени.

        Args:
            name: Имя клиента.

        Returns:
            MCPClientSpec или None если не найден.
        """
        return self._clients.get(name)

    async def call(self, client_name: str, tool_name: str, **params: Any) -> Any:
        """Вызывает tool на external MCP-сервере через WAF.

        Args:
            client_name: Имя клиента из реестра.
            tool_name: Имя tool на remote MCP.
            **params: Параметры tool.

        Returns:
            Результат вызова tool.

        Raises:
            KeyError: Если client_name не зарегистрирован.
            PermissionError: Если capability check failed.
            RuntimeError: Если HTTP client недоступен.
        """
        from anyio import BrokenResourceError

        spec = self._clients[client_name]

        # 1. Capability gate
        if spec.capability_required:
            _check_capability(spec.capability_required, client_name)

        # 2. Resolve HTTP client (OutboundHttpClient with WAF)
        http_client = await self._resolve_http_client(spec)

        # 3. Build request
        headers = dict(spec.headers)
        if spec.auth_provider == "api_key" and "X-API-Key" not in headers:
            api_key = await self._resolve_api_key(client_name)
            if api_key:
                headers["X-API-Key"] = api_key

        # 4. Execute via MCP protocol over HTTP
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": params},
        }

        try:
            response = await http_client.post(
                spec.url, json=payload, headers=headers, timeout=spec.timeout_s
            )
            response.raise_for_status()
            result = response.json()

            if "error" in result:
                logger.error(
                    "MCP external call error: client=%s tool=%s error=%s",
                    client_name,
                    tool_name,
                    result["error"],
                )
                return {"error": result["error"]}

            return result.get("result")

        except BrokenResourceError as exc:
            logger.error("MCP external call failed: %s", exc)
            return {"error": str(exc)}

    async def _resolve_http_client(self, spec: MCPClientSpec) -> Any:
        """Резолвит OutboundHttpClient с WAF policy.

        Args:
            spec: Спецификация клиента.

        Returns:
            OutboundHttpClient instance.
        """
        if self._http_client is not None:
            return self._http_client

        try:
            from src.backend.core.net.outbound_http import OutboundHttpClient

            waf_policy = spec.waf_policy if spec.waf_policy else "strict"
            self._http_client = OutboundHttpClient(waf_policy=waf_policy)
            return self._http_client
        except ImportError as exc:
            raise RuntimeError(
                "OutboundHttpClient is required for MCP registry WAF compliance. "
                "Ensure src.backend.core.net.outbound_http is importable."
            ) from exc

    async def _resolve_api_key(self, client_name: str) -> str | None:
        """Резолвит API key для клиента из secrets.

        Args:
            client_name: Имя клиента.

        Returns:
            API key string или None.
        """
        try:
            from src.backend.core.interfaces.secrets import SecretsBackend

            # Try to get from secrets backend
            broker: SecretsBackend | None = None
            try:
                from src.backend.infrastructure.security.vault_secrets import (
                    VaultSecretsBackend,
                )

                broker = VaultSecretsBackend()
            except Exception as _:
                try:
                    from src.backend.infrastructure.security.env_secrets import (
                        EnvSecretsBackend,
                    )

                    broker = EnvSecretsBackend()
                except Exception as exc:
                    logger.debug("EnvSecretsBackend init failed: %s", exc)

            if broker is not None:
                result = await broker.get_secret(f"mcp/{client_name}/api_key")
                return result
            return None
        except Exception as _:
            return None


def _check_capability(capability: str, client_name: str) -> None:
    """Проверяет capability для outbound access.

    Args:
        capability: Required capability (e.g. "net.outbound.mcp.anthropic.com:external").
        client_name: Имя клиента для логирования.

    Raises:
        PermissionError: Если capability denied.
    """
    try:
        from src.backend.core.security.capability_gate import CapabilityGate

        gate = CapabilityGate.get_instance()
        plugin = "mcp_client_registry"
        scope = client_name

        if not gate.check(plugin, capability, scope):
            logger.warning(
                "MCP external client capability denied: %s (%s)",
                capability,
                client_name,
            )
            raise PermissionError(
                f"Capability '{capability}' denied for MCP client '{client_name}'"
            )
    except ImportError:
        logger.debug("CapabilityGate not available, skipping capability check")


# Global registry instance
mcp_client_registry = MCPClientRegistry()
