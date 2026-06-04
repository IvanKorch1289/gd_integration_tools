"""Tests for src.backend.services.routes.route_authz."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.routes.route_authz import check_route_permission


@dataclass
class FakeDecision:
    allowed: bool
    reasons: list[Any]


@pytest.mark.unit
class TestCheckRoutePermission:
    """Tests for check_route_permission."""

    @pytest.mark.asyncio
    async def test_empty_permissions_returns_true(self) -> None:
        allowed, reason = await check_route_permission(
            route_id="r1", principal="user-1", permissions=()
        )
        assert allowed is True
        assert reason == "no_permissions_required"

    @pytest.mark.asyncio
    async def test_gateway_unavailable_raises_runtime_error(self) -> None:
        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            side_effect=ImportError("no module"),
        ):
            with pytest.raises(RuntimeError, match="AuthorizationGateway unavailable"):
                await check_route_permission(
                    route_id="r1", principal="user-1", permissions=("role:admin",)
                )

    @pytest.mark.asyncio
    async def test_gateway_none_returns_false(self) -> None:
        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            return_value=None,
        ):
            allowed, reason = await check_route_permission(
                route_id="r1", principal="user-1", permissions=("role:admin",)
            )
            assert allowed is False
            assert "authorization_gateway_not_registered" in reason

    @pytest.mark.asyncio
    async def test_allowed_decision(self) -> None:
        gateway = MagicMock()
        gateway._capability_gateway = MagicMock()
        gateway.permission_step = MagicMock(return_value="policy")

        authz_instance = MagicMock()
        authz_instance.authorize = AsyncMock(
            return_value=FakeDecision(allowed=True, reasons=[])
        )

        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            return_value=gateway,
        ):
            with patch(
                "src.backend.services.routes.route_authz.AuthorizationGateway",
                return_value=authz_instance,
            ):
                allowed, reason = await check_route_permission(
                    route_id="r1", principal="user-1", permissions=("role:admin",)
                )
                assert allowed is True
                assert reason == "allowed"

    @pytest.mark.asyncio
    async def test_denied_decision(self) -> None:
        gateway = MagicMock()
        gateway._capability_gateway = MagicMock()
        gateway.permission_step = MagicMock(return_value="policy")

        @dataclass
        class FakeReason:
            outcome: str
            source: str
            detail: str

        authz_instance = MagicMock()
        authz_instance.authorize = AsyncMock(
            return_value=FakeDecision(
                allowed=False,
                reasons=[
                    FakeReason(outcome="deny", source="policy", detail="no_access")
                ],
            )
        )

        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            return_value=gateway,
        ):
            with patch(
                "src.backend.services.routes.route_authz.AuthorizationGateway",
                return_value=authz_instance,
            ):
                allowed, reason = await check_route_permission(
                    route_id="r1", principal="user-1", permissions=("role:admin",)
                )
                assert allowed is False
                assert "no_access" in reason

    @pytest.mark.asyncio
    async def test_authorize_exception_returns_false(self) -> None:
        gateway = MagicMock()
        gateway._capability_gateway = MagicMock()
        gateway.permission_step = MagicMock(return_value="policy")

        authz_instance = MagicMock()
        authz_instance.authorize = MagicMock(side_effect=RuntimeError("conn failed"))

        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            return_value=gateway,
        ):
            with patch(
                "src.backend.services.routes.route_authz.AuthorizationGateway",
                return_value=authz_instance,
            ):
                allowed, reason = await check_route_permission(
                    route_id="r1", principal="user-1", permissions=("role:admin",)
                )
                assert allowed is False
                assert "authorization_check_error" in reason

    @pytest.mark.asyncio
    async def test_context_includes_route_id(self) -> None:
        gateway = MagicMock()
        gateway._capability_gateway = MagicMock()
        gateway.permission_step = MagicMock(return_value="policy")

        authz_instance = MagicMock()
        authz_instance.authorize = MagicMock(
            return_value=FakeDecision(allowed=True, reasons=[])
        )

        with patch(
            "src.backend.services.routes.route_authz._resolve_authz_gateway",
            return_value=gateway,
        ):
            with patch(
                "src.backend.services.routes.route_authz.AuthorizationGateway",
                return_value=authz_instance,
            ):
                await check_route_permission(
                    route_id="my_route",
                    principal="user-1",
                    permissions=("role:admin",),
                    context={"extra": "data"},
                )
                call_kwargs = authz_instance.authorize.call_args.kwargs
                assert call_kwargs["resource"] == "route:my_route"
                assert call_kwargs["context"]["route_id"] == "my_route"
                assert call_kwargs["context"]["extra"] == "data"
