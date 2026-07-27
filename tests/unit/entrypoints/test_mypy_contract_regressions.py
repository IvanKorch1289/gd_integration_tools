"""Regression tests for entrypoint contracts fixed during strict mypy cleanup."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.backend.core.auth.jwt_backend import JwtClaims
from src.backend.entrypoints.middlewares.ai_tool_whitelist import (
    _default_whitelist_check,
)
from src.backend.entrypoints.middlewares.observability import _emit_prometheus
from src.backend.entrypoints.webhook.transformer import RelayRule, WebhookRelay
from src.backend.entrypoints.websocket.ws_auth import WSAuthenticator


def malformed_retry(*_args: object, **_kwargs: object):
    """Replace a retry-wrapped sender with a malformed provider result."""

    def decorator(_func: object):
        async def malformed_attempt() -> object:
            return "invalid-result"

        return malformed_attempt

    return decorator


def test_default_whitelist_check_treats_non_raising_check_as_allowed() -> None:
    """CapabilityGate.check returns None on allow; absence of an error is success."""
    with patch("src.backend.core.security.capabilities.CapabilityGate") as gate_type:
        assert _default_whitelist_check("tenant-a", "search") is True

    gate_type.return_value.check.assert_called_once_with(
        "tenant-a",
        "agent.tools.invoke.search",
        "tool:search",
    )


def test_default_whitelist_check_fails_closed_on_check_error() -> None:
    with patch("src.backend.core.security.capabilities.CapabilityGate") as gate_type:
        gate_type.return_value.check.side_effect = RuntimeError("policy unavailable")
        assert _default_whitelist_check("tenant-a", "search") is False


async def test_authenticate_jwt_awaits_async_decode() -> None:
    decode = AsyncMock(
        return_value=JwtClaims(
            sub="user-1",
            iss=None,
            aud=None,
            exp=None,
            jti="token-1",
            raw={"groups": ["operators"]},
        )
    )
    backend = SimpleNamespace(decode=decode)

    with patch(
        "src.backend.core.auth.jwt_backend.JwtBackend",
        return_value=backend,
    ):
        session = await WSAuthenticator().authenticate_jwt("header.payload.signature")

    decode.assert_awaited_once_with("header.payload.signature")
    assert session.principal == "user-1"
    assert session.allowed_groups == {"operators"}


async def test_webhook_sender_non_dict_result_goes_to_dlq() -> None:
    relay = WebhookRelay()
    dlq_push = AsyncMock()

    def malformed_retry(*_args: object, **_kwargs: object):
        def decorator(_func: object):
            async def malformed_attempt() -> object:
                return "invalid-result"

            return malformed_attempt

        return decorator

    with (
        patch.object(relay, "_dlq_push", dlq_push),
        patch(
            "src.backend.core.resilience.retry.make_async_retry",
            malformed_retry,
        ),
    ):
        result = await relay._send_with_retry(
            RelayRule(id="rule-1", target_url="https://example.test"),
            {"event": "created"},
        )

    assert result["status"] == "dlq"
    assert "non-dict" in result["error"]
    dlq_push.assert_awaited_once()


def test_webhook_transform_non_dict_result_is_filtered_out() -> None:
    relay = WebhookRelay()
    rule = RelayRule(id="rule-1", jmespath_expression="items[0]")

    assert relay._transform({"items": ["scalar"]}, rule) is None


def test_prometheus_emitter_is_noop_when_optional_metrics_module_missing() -> None:
    with patch(
        "src.backend.entrypoints.middlewares.observability.importlib.import_module",
        side_effect=ImportError("optional module unavailable"),
    ):
        _emit_prometheus({"method": "GET", "status_code": 200})


async def test_clickhouse_admin_provider_is_awaitable_singleton() -> None:
    from src.backend.infrastructure.clients.storage import clickhouse_admin_client

    client = object()
    get_async_client = AsyncMock(return_value=client)
    fake_module = SimpleNamespace(get_async_client=get_async_client)

    with (
        patch.object(clickhouse_admin_client, "_admin_client", None),
        patch.dict("sys.modules", {"clickhouse_connect": fake_module}),
    ):
        first = await clickhouse_admin_client.get_admin_clickhouse_client()
        second = await clickhouse_admin_client.get_admin_clickhouse_client()

    assert first is client
    assert second is client
    get_async_client.assert_awaited_once()
