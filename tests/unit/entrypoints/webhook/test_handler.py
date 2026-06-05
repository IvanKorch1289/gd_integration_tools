"""Unit tests for webhook handler."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from src.backend.entrypoints.webhook.handler import (
    CreateSubscriptionRequest,
    _check_rate_limit,
    create_subscription,
    delete_subscription,
    list_subscriptions,
    receive_webhook,
    send_webhook_event,
)


class TestCheckRateLimit:
    @pytest.mark.asyncio
    async def test_import_error_ignored(self) -> None:
        with patch(
            "src.backend.core.di.providers.get_rate_limit_classes_provider",
            side_effect=ImportError,
        ):
            await _check_rate_limit("ip1")

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self) -> None:
        with (
            patch(
                "src.backend.core.di.providers.get_rate_limit_classes_provider"
            ) as mock_cls,
            patch(
                "src.backend.core.di.providers.get_rate_limiter_provider"
            ) as mock_lim,
        ):
            RL = MagicMock()
            Exc = type("RateLimitExceeded", (Exception,), {"retry_after": 10})
            mock_cls.return_value = (RL, Exc)
            limiter = AsyncMock()
            limiter.check.side_effect = Exc()
            mock_lim.return_value = limiter
            with pytest.raises(HTTPException) as exc_info:
                await _check_rate_limit("ip1")
            assert exc_info.value.status_code == 429


class TestCreateSubscription:
    @pytest.mark.asyncio
    async def test_create_success(self) -> None:
        with (
            patch(
                "src.backend.entrypoints.webhook.handler._require_auth_dep",
                return_value=MagicMock(),
            ),
            patch(
                "src.backend.dsl.engine.processors.scraping._validate_url"
            ) as mock_val,
        ):
            mock_val.return_value = None
            body = CreateSubscriptionRequest(
                event_type="order.created", target_url="https://example.com/hook"
            )
            with patch(
                "src.backend.entrypoints.webhook.handler.webhook_registry"
            ) as mock_reg:
                sub = MagicMock()
                sub.id = "sub1"
                sub.event_type = "order.created"
                sub.target_url = "https://example.com/hook"
                mock_reg.add.return_value = sub
                result = await create_subscription(body, auth=MagicMock())
                assert result["id"] == "sub1"

    @pytest.mark.asyncio
    async def test_create_invalid_url(self) -> None:
        with (
            patch(
                "src.backend.entrypoints.webhook.handler._require_auth_dep",
                return_value=MagicMock(),
            ),
            patch(
                "src.backend.dsl.engine.processors.scraping._validate_url",
                side_effect=ValueError("bad url"),
            ),
        ):
            body = CreateSubscriptionRequest(
                event_type="order.created", target_url="bad"
            )
            with pytest.raises(HTTPException) as exc_info:
                await create_subscription(body, auth=MagicMock())
            assert exc_info.value.status_code == 400


class TestDeleteSubscription:
    @pytest.mark.asyncio
    async def test_delete_success(self) -> None:
        with (
            patch(
                "src.backend.entrypoints.webhook.handler._require_auth_dep",
                return_value=MagicMock(),
            ),
            patch(
                "src.backend.entrypoints.webhook.handler.webhook_registry"
            ) as mock_reg,
        ):
            mock_reg.remove.return_value = None
            result = await delete_subscription("sub1", auth=MagicMock())
            assert result["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        with (
            patch(
                "src.backend.entrypoints.webhook.handler._require_auth_dep",
                return_value=MagicMock(),
            ),
            patch(
                "src.backend.entrypoints.webhook.handler.webhook_registry"
            ) as mock_reg,
        ):
            mock_reg.remove.side_effect = KeyError("missing")
            with pytest.raises(HTTPException) as exc_info:
                await delete_subscription("sub1", auth=MagicMock())
            assert exc_info.value.status_code == 404


class TestListSubscriptions:
    @pytest.mark.asyncio
    async def test_list(self) -> None:
        with (
            patch(
                "src.backend.entrypoints.webhook.handler._require_auth_dep",
                return_value=MagicMock(),
            ),
            patch(
                "src.backend.entrypoints.webhook.handler.webhook_registry"
            ) as mock_reg,
        ):
            mock_reg.list_all.return_value = [{"id": "s1"}]
            result = await list_subscriptions(auth=MagicMock())
            assert result == [{"id": "s1"}]


class TestReceiveWebhook:
    @pytest.mark.asyncio
    async def test_receive_success(self) -> None:
        request = MagicMock(spec=Request)
        request.client.host = "1.2.3.4"
        request.body = AsyncMock(return_value=b'{"x":1}')
        request.headers = {}
        with (
            patch(
                "src.backend.entrypoints.webhook.handler.webhook_registry"
            ) as mock_reg,
            patch(
                "src.backend.entrypoints.webhook.handler.dispatch_action_or_dsl"
            ) as mock_bridge,
        ):
            mock_reg.list_all.return_value = []
            mock_bridge.return_value = MagicMock(
                error_code="", success=True, error=None
            )
            result = await receive_webhook("order.created", request)
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_receive_not_found(self) -> None:
        request = MagicMock(spec=Request)
        request.client.host = "1.2.3.4"
        request.body = AsyncMock(return_value=b"{}")
        request.headers = {}
        with patch(
            "src.backend.entrypoints.webhook.handler.dispatch_action_or_dsl"
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                error_code="action_not_found", success=False, error="not found"
            )
            with pytest.raises(HTTPException) as exc_info:
                await receive_webhook("missing", request)
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_receive_invalid_signature(self) -> None:
        request = MagicMock(spec=Request)
        request.client.host = "1.2.3.4"
        request.body = AsyncMock(return_value=b'{"x":1}')
        request.headers = {"X-Webhook-Signature": "bad"}
        with patch(
            "src.backend.entrypoints.webhook.handler.webhook_registry"
        ) as mock_reg:
            sub = {"event_type": "order.created", "secret": "secret", "id": "s1"}
            mock_reg.list_all.return_value = [sub]
            with pytest.raises(HTTPException) as exc_info:
                await receive_webhook("order.created", request)
            assert exc_info.value.status_code == 401


class TestSendWebhookEvent:
    @pytest.mark.asyncio
    async def test_send_no_subscriptions(self) -> None:
        with patch(
            "src.backend.entrypoints.webhook.handler.webhook_registry"
        ) as mock_reg:
            mock_reg.get_by_event.return_value = []
            result = await send_webhook_event("order.created", {"x": 1})
            assert result == []

    @pytest.mark.asyncio
    async def test_send_success(self) -> None:
        sub = MagicMock()
        sub.secret = None
        sub.id = "s1"
        sub.target_url = "https://example.com/hook"
        with (
            patch(
                "src.backend.entrypoints.webhook.handler.webhook_registry"
            ) as mock_reg,
            patch("src.backend.core.net.OutboundHttpClient") as mock_client,
        ):
            mock_reg.get_by_event.return_value = [sub]
            session = AsyncMock()
            resp = MagicMock()
            resp.status_code = 200
            session.post.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await send_webhook_event("order.created", {"x": 1})
            assert len(result) == 1
            assert result[0]["success"] is True
