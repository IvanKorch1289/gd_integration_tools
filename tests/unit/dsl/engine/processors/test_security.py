"""Unit tests for AuthValidateProcessor."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.security import AuthValidateProcessor


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestAuthValidateProcessor:
    @pytest.mark.asyncio
    async def test_none_method(self) -> None:
        proc = AuthValidateProcessor(["none"])
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        ctx = exchange.properties.get("auth")
        assert isinstance(ctx, AuthContext)
        assert ctx.method == AuthMethod.NONE

    @pytest.mark.asyncio
    async def test_no_request_skips(self) -> None:
        proc = AuthValidateProcessor(["jwt"])
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        ctx = exchange.properties.get("auth")
        assert isinstance(ctx, AuthContext)
        assert ctx.method == AuthMethod.NONE

    @pytest.mark.asyncio
    async def test_successful_auth(self) -> None:
        proc = AuthValidateProcessor(["jwt"])
        exchange = _ex({})
        exchange.set_property("request", MagicMock())
        with patch(
            "src.backend.dsl.engine.processors.security._load_verifiers"
        ) as mock_load:
            verifier = AsyncMock(return_value=AuthContext(AuthMethod.JWT, "user1"))
            mock_load.return_value = {AuthMethod.JWT: verifier}
            await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties["auth"].principal == "user1"

    @pytest.mark.asyncio
    async def test_required_fails(self) -> None:
        proc = AuthValidateProcessor(["jwt"], required=True)
        exchange = _ex({})
        exchange.set_property("request", MagicMock())
        with patch(
            "src.backend.dsl.engine.processors.security._load_verifiers"
        ) as mock_load:
            mock_load.return_value = {}
            await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.stopped
        assert exchange.error is not None

    @pytest.mark.asyncio
    async def test_unknown_method(self) -> None:
        proc = AuthValidateProcessor(["unknown_method"])
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.stopped
        assert "неизвестный AuthMethod" in exchange.error

    def test_to_spec(self) -> None:
        proc = AuthValidateProcessor(["jwt", "api_key"], result_property="auth_ctx")
        spec = proc.to_spec()
        assert spec == {
            "auth": {
                "methods": ["jwt", "api_key"],
                "result_property": "auth_ctx",
                "required": True,
            }
        }
