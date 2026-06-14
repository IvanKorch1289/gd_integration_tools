"""Tests for require_sso_auth decorator (S125 W3).

Validates SSO session auth + groups-to-capabilities RBAC.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.core.auth import (
    AuthContext,
    AuthMethod,
    GroupsToCapabilities,
    IdpConfig,
    SsoRegistry,
)
from src.backend.core.auth.sso_registry import SsoRegistryError
from src.backend.core.auth.require_sso_auth import (
    RequireSsoAuthError,
    require_sso_auth,
    require_sso_capability,
)


def _make_auth_context(
    method: AuthMethod = AuthMethod.SAML,
    principal: str = "alice",
    metadata: dict[str, Any] | None = None,
) -> AuthContext:
    """Build AuthContext for tests."""
    return AuthContext(method=method, principal=principal, metadata=metadata)


def _make_idp_config(
    mappings: dict[str, list[str]] | None = None,
) -> IdpConfig:
    """Build IdpConfig with given group→capability mappings."""
    return IdpConfig(
        entity_id="https://idp.example.com",
        sso_url="https://idp.example.com/sso",
        x509_cert="-----BEGIN CERTIFICATE-----\nMIIB...\n-----END CERTIFICATE-----",
        groups_to_capabilities=GroupsToCapabilities(mappings=mappings or {}),
    )


@pytest.fixture
def mock_registry() -> AsyncMock:
    """Mock SsoRegistry returning IdpConfig with known mappings."""
    registry = AsyncMock(spec=SsoRegistry)
    registry.get = AsyncMock(
        return_value=_make_idp_config(
            mappings={"admins": ["admin:read", "admin:write"]},
        )
    )
    return registry


class TestRequireSsoAuthDecorator:
    """require_sso_auth(registry) returns a decorator."""

    @pytest.mark.asyncio
    async def test_passes_when_auth_method_is_saml(
        self, mock_registry: AsyncMock
    ) -> None:
        @require_sso_auth(mock_registry)
        async def handler(auth: AuthContext) -> str:
            return f"ok:{auth.principal}"

        auth = _make_auth_context(
            method=AuthMethod.SAML,
            principal="alice",
            metadata={"tenant_id": "acme", "groups": ["admins"]},
        )
        result = await handler(auth=auth)
        assert result == "ok:alice"

    @pytest.mark.asyncio
    async def test_rejects_non_saml_auth_method(
        self, mock_registry: AsyncMock
    ) -> None:
        @require_sso_auth(mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        auth = _make_auth_context(method=AuthMethod.JWT)
        with pytest.raises(RequireSsoAuthError, match="jwt"):
            await handler(auth=auth)

    @pytest.mark.asyncio
    async def test_resolves_groups_via_registry(
        self, mock_registry: AsyncMock
    ) -> None:
        """Registry должен быть вызван с tenant_id из metadata."""
        @require_sso_auth(mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        auth = _make_auth_context(
            metadata={"tenant_id": "bank-1", "groups": ["admins"]}
        )
        await handler(auth=auth)
        mock_registry.get.assert_awaited_once_with("bank-1")

    @pytest.mark.asyncio
    async def test_propagates_registry_error(
        self, mock_registry: AsyncMock
    ) -> None:
        """SsoRegistryError должен propagate."""
        mock_registry.get.side_effect = SsoRegistryError("vault misconfig")

        @require_sso_auth(mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        auth = _make_auth_context(
            metadata={"tenant_id": "acme", "groups": ["admins"]}
        )
        with pytest.raises(SsoRegistryError):
            await handler(auth=auth)

    @pytest.mark.asyncio
    async def test_raises_when_tenant_id_missing(
        self, mock_registry: AsyncMock
    ) -> None:
        @require_sso_auth(mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        auth = _make_auth_context(
            method=AuthMethod.SAML, metadata={"groups": ["admins"]}
        )
        with pytest.raises(RequireSsoAuthError, match="tenant_id"):
            await handler(auth=auth)

    @pytest.mark.asyncio
    async def test_raises_when_registry_returns_none(
        self, mock_registry: AsyncMock
    ) -> None:
        """Если IdpConfig не найден — fail-closed."""
        mock_registry.get.return_value = None

        @require_sso_auth(mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        auth = _make_auth_context(
            metadata={"tenant_id": "unknown", "groups": ["admins"]}
        )
        with pytest.raises(RequireSsoAuthError, match="IdP config"):
            await handler(auth=auth)


class TestRequireSsoCapabilityDecorator:
    """require_sso_capability(cap, registry) — granular capability check."""

    @pytest.mark.asyncio
    async def test_passes_when_user_has_capability(
        self, mock_registry: AsyncMock
    ) -> None:
        @require_sso_capability("admin:read", mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        auth = _make_auth_context(
            metadata={"tenant_id": "acme", "groups": ["admins"]}
        )
        result = await handler(auth=auth)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_rejects_when_user_lacks_capability(
        self, mock_registry: AsyncMock
    ) -> None:
        @require_sso_capability("admin:write", mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        # User has "users" group, no mapping -> no caps
        mock_registry.get.return_value = _make_idp_config(
            mappings={"admins": ["admin:read", "admin:write"]},
        )
        auth = _make_auth_context(
            metadata={"tenant_id": "acme", "groups": ["users"]}
        )
        with pytest.raises(RequireSsoAuthError, match="admin:write"):
            await handler(auth=auth)

    @pytest.mark.asyncio
    async def test_rejects_non_saml_method(
        self, mock_registry: AsyncMock
    ) -> None:
        @require_sso_capability("admin:read", mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        auth = _make_auth_context(
            method=AuthMethod.API_KEY,
            metadata={"tenant_id": "acme", "groups": ["admins"]},
        )
        with pytest.raises(RequireSsoAuthError, match="api_key"):
            await handler(auth=auth)

    @pytest.mark.asyncio
    async def test_handles_missing_groups_claim(
        self, mock_registry: AsyncMock
    ) -> None:
        @require_sso_capability("admin:read", mock_registry)
        async def handler(auth: AuthContext) -> str:
            return "ok"

        # No "groups" key in metadata
        auth = _make_auth_context(
            metadata={"tenant_id": "acme"}
        )
        with pytest.raises(RequireSsoAuthError, match="admin:read"):
            await handler(auth=auth)


class TestDecoratorMetadata:
    """Decorator must preserve function metadata (functools.wraps)."""

    @pytest.mark.asyncio
    async def test_preserves_function_name_and_doc(
        self, mock_registry: AsyncMock
    ) -> None:
        @require_sso_auth(mock_registry)
        async def my_handler(auth: AuthContext) -> str:
            """Custom docstring."""
            return "ok"

        assert my_handler.__name__ == "my_handler"
        assert my_handler.__doc__ == "Custom docstring."
