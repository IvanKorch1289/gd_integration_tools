"""Tests for dsl/integration_gateway public API."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.integration_gateway import (
    ChannelInterceptor,
    MessagingGateway,
    VersionedRoute,
)


class TestMessagingGateway:
    @pytest.mark.asyncio
    async def test_invoke(self) -> None:
        gw = MessagingGateway(route_id="orders.create")
        mock_dsl = MagicMock()
        mock_dsl.dispatch = AsyncMock(return_value={"ok": True})
        with patch("src.backend.dsl.service.get_dsl_service", return_value=mock_dsl):
            result = await gw.invoke({"order_id": 1})
        mock_dsl.dispatch.assert_awaited_once_with(
            route_id="orders.create", body={"order_id": 1}, headers={}
        )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_invoke_with_headers(self) -> None:
        gw = MessagingGateway(route_id="orders.create")
        mock_dsl = MagicMock()
        mock_dsl.dispatch = AsyncMock(return_value=None)
        with patch("src.backend.dsl.service.get_dsl_service", return_value=mock_dsl):
            await gw.invoke({}, headers={"x-tenant": "bank"})
        mock_dsl.dispatch.assert_awaited_once_with(
            route_id="orders.create", body={}, headers={"x-tenant": "bank"}
        )


class TestChannelInterceptor:
    def test_defaults(self) -> None:
        ci = ChannelInterceptor()
        assert ci.pre_send is None
        assert ci.post_send is None


class TestVersionedRoute:
    def test_resolve(self) -> None:
        vr = VersionedRoute(
            base_id="orders", versions={"v1": "orders.v1", "v2": "orders.v2"}
        )
        assert vr.resolve("v2") == "orders.v2"

    def test_is_deprecated(self) -> None:
        vr = VersionedRoute(
            base_id="orders", versions={"v1": "orders.v1"}, deprecated={"v1"}
        )
        assert vr.is_deprecated("v1") is True
        assert vr.is_deprecated("v2") is False

    def test_post_init_defaults(self) -> None:
        vr = VersionedRoute(base_id="x", versions={})
        assert vr.deprecated == set()
        assert vr.sunset_dates == {}
